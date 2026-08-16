// Find WHO writes a byte of GBA memory: run the ROM with scripted A-presses,
// arm a write watchpoint at a given frame, and print the CPU state at each
// hit. This is how the name-entry screen's glyph renderer was located.
//
// Usage: gbawatch ROM --frames N --mash M --until F --arm FRAME:ADDR [--hits K]
//   --mash M   press A for 4 frames every M frames, stopping at --until.
//   --press    FRAME:KEY[:HELD], a one-off press, same spelling as gbashot.
//              Screens reached with the d-pad (the battle parts panel) need
//              these: the redraw only happens on the frame the key changes it.
//   --arm      at FRAME, set a write watchpoint on ADDR (hex bus address).

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <mgba/core/core.h>
#include <mgba/core/config.h>
#include <mgba/gba/core.h>
#include <mgba/debugger/debugger.h>
#include <mgba/internal/arm/arm.h>
#include <mgba/core/serialize.h>
#include <mgba-util/vfs.h>
#include <mgba/internal/arm/debugger/debugger.h>

#define MAX_PRESSES 64

struct press {
	unsigned frame;
	unsigned keys;
	unsigned held;
};

static unsigned hits_left = 10;
static struct mDebugger debugger;

static unsigned key_bit(const char* name) {
	static const char* names[] = {"a", "b", "select", "start",
	                              "right", "left", "up", "down", "r", "l"};
	for (unsigned i = 0; i < 10; ++i) {
		if (!strcmp(name, names[i])) {
			return 1u << i;
		}
	}
	return 0;
}

static void on_init(struct mDebugger* dbg) { (void) dbg; }
static void on_deinit(struct mDebugger* dbg) { (void) dbg; }

static void on_paused(struct mDebugger* dbg) {
	struct ARMCore* cpu = dbg->core->cpu;
	printf("hit: pc=%08X lr=%08X r0=%08X r1=%08X r2=%08X r3=%08X r4=%08X r5=%08X\n",
	       cpu->gprs[15], cpu->gprs[14], cpu->gprs[0], cpu->gprs[1],
	       cpu->gprs[2], cpu->gprs[3], cpu->gprs[4], cpu->gprs[5]);
	// Dump the bytes around r4: the compact-string renderer keeps its
	// source pointer there, and that is usually what we came for.
	printf("r4 bytes:");
	for (int k = -8; k < 16; ++k) {
		printf(" %02X", (unsigned) dbg->core->busRead8(dbg->core, cpu->gprs[4] + k));
	}
	printf("\n");
	fflush(stdout);
	if (hits_left && !--hits_left) {
		// Enough seen: let the run finish without stopping again.
		struct mWatchpointList list;
		mWatchpointListInit(&list, 0);
		dbg->platform->listWatchpoints(dbg->platform, &list);
		for (size_t i = 0; i < mWatchpointListSize(&list); ++i) {
			dbg->platform->clearBreakpoint(
				dbg->platform, mWatchpointListGetPointer(&list, i)->id);
		}
		mWatchpointListDeinit(&list);
	}
	dbg->state = DEBUGGER_RUNNING;
}

static void on_entered(struct mDebugger* dbg, enum mDebuggerEntryReason reason,
                       struct mDebuggerEntryInfo* info) {
	(void) dbg;
	if (reason == DEBUGGER_ENTER_WATCHPOINT && info) {
		printf("watchpoint at %08X new=%08X\n", info->address, info->type.wp.newValue);
	}
}

int main(int argc, char** argv) {
	const char* rom_path = argv[1];
	unsigned frames = 3000;
	unsigned mash = 45;
	unsigned until = 2565;
	unsigned arm_frame = 2600;
	uint32_t arm_addr = 0x06001B80;
	const char* loadstate_path = NULL;
	struct press presses[MAX_PRESSES];
	unsigned press_count = 0;

	for (int i = 2; i < argc; ++i) {
		if (!strcmp(argv[i], "--frames") && i + 1 < argc) {
			frames = (unsigned) atoi(argv[++i]);
		} else if (!strcmp(argv[i], "--mash") && i + 1 < argc) {
			mash = (unsigned) atoi(argv[++i]);
		} else if (!strcmp(argv[i], "--until") && i + 1 < argc) {
			until = (unsigned) atoi(argv[++i]);
		} else if (!strcmp(argv[i], "--hits") && i + 1 < argc) {
			hits_left = (unsigned) atoi(argv[++i]);
		} else if (!strcmp(argv[i], "--loadstate") && i + 1 < argc) {
			loadstate_path = argv[++i];
		} else if (!strcmp(argv[i], "--press") && i + 1 < argc && press_count < MAX_PRESSES) {
			char* spec = argv[++i];
			char* first = strchr(spec, ':');
			if (!first) {
				fprintf(stderr, "--press wants FRAME:KEY[:HELD]\n");
				return 2;
			}
			*first = 0;
			char* second = strchr(first + 1, ':');
			unsigned held = 2;
			if (second) {
				*second = 0;
				held = (unsigned) atoi(second + 1);
			}
			unsigned bit = key_bit(first + 1);
			if (!bit) {
				fprintf(stderr, "unknown key %s\n", first + 1);
				return 2;
			}
			presses[press_count].frame = (unsigned) atoi(spec);
			presses[press_count].keys = bit;
			presses[press_count].held = held ? held : 1;
			++press_count;
		} else if (!strcmp(argv[i], "--arm") && i + 1 < argc) {
			char* spec = argv[++i];
			char* colon = strchr(spec, ':');
			if (!colon) {
				fprintf(stderr, "--arm wants FRAME:HEXADDR\n");
				return 2;
			}
			*colon = 0;
			arm_frame = (unsigned) atoi(spec);
			arm_addr = (uint32_t) strtoul(colon + 1, NULL, 16);
		}
	}

	struct mCore* core = mCoreFind(rom_path);
	core->init(core);
	mCoreInitConfig(core, NULL);
	unsigned w, h;
	core->desiredVideoDimensions(core, &w, &h);
	color_t* buffer = calloc(w * h, sizeof(color_t));
	core->setVideoBuffer(core, buffer, w);
	if (!mCoreLoadFile(core, rom_path)) {
		fprintf(stderr, "cannot load %s\n", rom_path);
		return 1;
	}

	memset(&debugger, 0, sizeof(debugger));
	debugger.type = DEBUGGER_CUSTOM;
	debugger.platform = ARMDebuggerPlatformCreate();
	debugger.paused = on_paused;
	debugger.entered = on_entered;
	debugger.init = on_init;
	debugger.deinit = on_deinit;
	mDebuggerAttach(&debugger, core);

	core->reset(core);

	if (loadstate_path) {
		struct VFile* vf = VFileOpen(loadstate_path, O_RDONLY);
		if (!vf || !mCoreLoadStateNamed(core, vf, SAVESTATE_ALL & ~SAVESTATE_SAVEDATA)) {
			fprintf(stderr, "cannot load state %s\n", loadstate_path);
			return 1;
		}
		vf->close(vf);
	}

	bool armed = false;
	for (unsigned frame = 0; frame <= frames; ++frame) {
		unsigned keys = 0;
		if (mash && frame <= until && (frame % mash) < 4) {
			keys = 1;  // A
		}
		for (unsigned i = 0; i < press_count; ++i) {
			if (frame >= presses[i].frame &&
			    frame < presses[i].frame + presses[i].held) {
				keys |= presses[i].keys;
			}
		}
		core->setKeys(core, keys);
		if (!armed && frame >= arm_frame) {
			struct mWatchpoint wp = {
				.id = 0, .address = arm_addr, .segment = -1,
				.type = WATCHPOINT_WRITE, .condition = NULL,
			};
			ssize_t id = debugger.platform->setWatchpoint(debugger.platform, &wp);
			printf("armed watchpoint %zd at %08X (frame %u)\n", id, arm_addr, frame);
			fflush(stdout);
			armed = true;
		}
		mDebuggerRunFrame(&debugger);
	}
	core->deinit(core);
	return 0;
}

// Run a GBA ROM headless and write frames out as PNG.
//
// Checking a translation by eye means getting to the screen that shows it, and
// there is no way to do that from a build script without actually running the
// game. This links against libmgba, presses buttons on a schedule and dumps
// whatever is on screen, so a test can assert on pixels.
//
// Build:  make -C tools
// Usage:  gbashot ROM --frames N --shot FRAME:FILE.png [--press FRAME:KEY[:HELD]]
//                     [--every N:KEY] [--watch MIN:MAX]
//
// Keys: a b select start right left up down r l
//
// --every presses a key for 4 frames every N frames, for mashing through
// dialogue. --watch scans EWRAM each frame for pointers into [MIN,MAX) of the
// cartridge and prints each distinct value the first frame it appears; pointing
// it at the script area tells you which scene the game is running, which is
// how the play order of the scripts was recovered.
//
// --dumpvram FRAME:FILE writes the display state at that frame: the LCD
// registers (0x04000000-0x5F), palette RAM (0x400), VRAM (0x18000) and OAM
// (0x400), concatenated in that order. It is how a screen's tiles are traced
// back to the compressed block in the ROM they were decompressed from.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <mgba/core/core.h>
#include <mgba/core/config.h>
#include <mgba/gba/core.h>
#include <mgba/core/serialize.h>
#include <mgba-util/vfs.h>
#include <mgba-util/png-io.h>

#define WIDTH 240
#define HEIGHT 160
#define MAX_EVENTS 256

struct shot {
	unsigned frame;
	const char* path;
};

struct vramdump {
	unsigned frame;
	const char* path;
};

struct press {
	unsigned frame;
	unsigned held;
	unsigned keys;
};

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

static bool write_png(const char* path, const color_t* pixels) {
	struct VFile* vf = VFileOpen(path, O_WRONLY | O_CREAT | O_TRUNC);
	if (!vf) {
		fprintf(stderr, "cannot write %s\n", path);
		return false;
	}
	png_structp png = PNGWriteOpen(vf);
	png_infop info = png ? PNGWriteHeader(png, WIDTH, HEIGHT) : NULL;
	bool ok = png && info;
	if (ok) {
		ok = PNGWritePixels(png, WIDTH, HEIGHT, WIDTH, pixels);
	}
	if (png) {
		PNGWriteClose(png, info);
	}
	vf->close(vf);
	return ok;
}

int main(int argc, char** argv) {
	if (argc < 2) {
		fprintf(stderr, "usage: %s ROM [--frames N] [--shot FRAME:FILE]"
		                " [--press FRAME:KEY[:HELD]]\n", argv[0]);
		return 2;
	}
	const char* rom_path = argv[1];
	unsigned frames = 600;
	struct shot shots[MAX_EVENTS];
	unsigned shot_count = 0;
	struct press presses[MAX_EVENTS];
	unsigned press_count = 0;
	struct vramdump dumps[MAX_EVENTS];
	unsigned dump_count = 0;
	unsigned every_n = 0;
	unsigned every_keys = 0;
	unsigned wander_n = 0;
	unsigned wander_start = 0;
	uint32_t watch_min = 0;
	uint32_t watch_max = 0;
	unsigned savestate_frame = 0;
	const char* savestate_path = NULL;
	const char* loadstate_path = NULL;

	for (int i = 2; i < argc; ++i) {
		if (!strcmp(argv[i], "--frames") && i + 1 < argc) {
			frames = (unsigned) atoi(argv[++i]);
		} else if (!strcmp(argv[i], "--shot") && i + 1 < argc && shot_count < MAX_EVENTS) {
			char* spec = argv[++i];
			char* colon = strchr(spec, ':');
			if (!colon) {
				fprintf(stderr, "--shot wants FRAME:FILE\n");
				return 2;
			}
			*colon = 0;
			shots[shot_count].frame = (unsigned) atoi(spec);
			shots[shot_count].path = colon + 1;
			++shot_count;
		} else if (!strcmp(argv[i], "--press") && i + 1 < argc && press_count < MAX_EVENTS) {
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
		} else if (!strcmp(argv[i], "--every") && i + 1 < argc) {
			char* spec = argv[++i];
			char* colon = strchr(spec, ':');
			if (!colon) {
				fprintf(stderr, "--every wants N:KEY\n");
				return 2;
			}
			*colon = 0;
			every_n = (unsigned) atoi(spec);
			every_keys = key_bit(colon + 1);
			if (!every_n || !every_keys) {
				fprintf(stderr, "bad --every\n");
				return 2;
			}
		} else if (!strcmp(argv[i], "--dumpvram") && i + 1 < argc && dump_count < MAX_EVENTS) {
			char* spec = argv[++i];
			char* colon = strchr(spec, ':');
			if (!colon) {
				fprintf(stderr, "--dumpvram wants FRAME:FILE\n");
				return 2;
			}
			*colon = 0;
			dumps[dump_count].frame = (unsigned) atoi(spec);
			dumps[dump_count].path = colon + 1;
			++dump_count;
		} else if (!strcmp(argv[i], "--savestate") && i + 1 < argc) {
			char* spec = argv[++i];
			char* colon = strchr(spec, ':');
			if (!colon) {
				fprintf(stderr, "--savestate wants FRAME:FILE\n");
				return 2;
			}
			*colon = 0;
			savestate_frame = (unsigned) atoi(spec);
			savestate_path = colon + 1;
		} else if (!strcmp(argv[i], "--loadstate") && i + 1 < argc) {
			loadstate_path = argv[++i];
		} else if (!strcmp(argv[i], "--wander") && i + 1 < argc) {
			char* spec = argv[++i];
			char* colon = strchr(spec, ':');
			if (colon) {
				*colon = 0;
				wander_start = (unsigned) atoi(spec);
				wander_n = (unsigned) atoi(colon + 1);
			} else {
				wander_n = (unsigned) atoi(spec);
			}
		} else if (!strcmp(argv[i], "--watch") && i + 1 < argc) {
			char* spec = argv[++i];
			char* colon = strchr(spec, ':');
			if (!colon) {
				fprintf(stderr, "--watch wants MIN:MAX (hex)\n");
				return 2;
			}
			*colon = 0;
			watch_min = (uint32_t) strtoul(spec, NULL, 16);
			watch_max = (uint32_t) strtoul(colon + 1, NULL, 16);
		} else {
			fprintf(stderr, "unknown option %s\n", argv[i]);
			return 2;
		}
	}

	if (wander_n && wander_n < 12) {
		wander_n = 12;  // below this the unsigned walk/talk windows underflow
	}

	struct mCore* core = mCoreFind(rom_path);
	if (!core) {
		fprintf(stderr, "not a ROM this build can run: %s\n", rom_path);
		return 1;
	}
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
	core->reset(core);

	if (loadstate_path) {
		struct VFile* vf = VFileOpen(loadstate_path, O_RDONLY);
		if (!vf || !mCoreLoadStateNamed(core, vf, SAVESTATE_ALL & ~SAVESTATE_SAVEDATA)) {
			fprintf(stderr, "cannot load state %s\n", loadstate_path);
			return 1;
		}
		vf->close(vf);
		printf("state loaded from %s\n", loadstate_path);
	}

	uint32_t* seen = calloc(4096, sizeof(uint32_t));
	unsigned seen_count = 0;

	int status = 0;
	for (unsigned frame = 0; frame <= frames; ++frame) {
		unsigned keys = 0;
		for (unsigned i = 0; i < press_count; ++i) {
			if (frame >= presses[i].frame && frame < presses[i].frame + presses[i].held) {
				keys |= presses[i].keys;
			}
		}
		if (every_n && (frame % every_n) < 4) {
			keys |= every_keys;
		}
		if (wander_n && frame >= wander_start) {
			// Walk in a direction for a stretch, poke A, turn. The stretch
			// lengths are co-prime-ish so the path does not settle into a
			// tight loop and ends up covering the walkable area.
			static const unsigned dirs[] = {1u << 7, 1u << 4, 1u << 6, 1u << 5,
			                                1u << 7, 1u << 5, 1u << 6, 1u << 4};
			unsigned phase = (frame / wander_n) % 8;
			unsigned within = frame % wander_n;
			if (within < wander_n - 8) {
				keys |= dirs[phase];   // down right up left ...
			} else if (within >= wander_n - 6 && within < wander_n - 2) {
				keys |= 1u << 0;       // A: talk to whatever is ahead
			}
		}
		core->setKeys(core, keys);
		core->runFrame(core);
		if (watch_max > watch_min) {
			for (uint32_t addr = 0x02000000; addr < 0x02040000; addr += 4) {
				uint32_t value = core->busRead32(core, addr);
				if (value < watch_min || value >= watch_max) {
					continue;
				}
				bool new_value = true;
				for (unsigned i = 0; i < seen_count; ++i) {
					if (seen[i] == value) {
						new_value = false;
						break;
					}
				}
				if (new_value && seen_count < 4096) {
					seen[seen_count++] = value;
					printf("watch 0x%08X @%u\n", value, frame);
					fflush(stdout);
				}
			}
		}
		for (unsigned i = 0; i < shot_count; ++i) {
			if (shots[i].frame == frame) {
				if (write_png(shots[i].path, buffer)) {
					printf("frame %u -> %s\n", frame, shots[i].path);
				} else {
					status = 1;
				}
			}
		}
		if (savestate_path && frame == savestate_frame) {
			struct VFile* vf = VFileOpen(savestate_path, O_WRONLY | O_CREAT | O_TRUNC);
			if (vf && mCoreSaveStateNamed(core, vf, SAVESTATE_ALL & ~SAVESTATE_SAVEDATA)) {
				printf("state saved to %s (frame %u)\n", savestate_path, frame);
			}
			if (vf) {
				vf->close(vf);
			}
		}
		for (unsigned i = 0; i < dump_count; ++i) {
			if (dumps[i].frame != frame) {
				continue;
			}
			bool ram = strstr(dumps[i].path, ".ram.") != NULL;
			FILE* handle = fopen(dumps[i].path, "wb");
			if (!handle) {
				fprintf(stderr, "cannot write %s\n", dumps[i].path);
				status = 1;
				continue;
			}
			// LCD registers, palette, VRAM, OAM — busRead16 keeps mGBA's
			// memory access rules honest (VRAM has no byte reads anyway).
			static const struct { uint32_t base; uint32_t length; } vregions[] = {
				{0x04000000, 0x60},
				{0x05000000, 0x400},
				{0x06000000, 0x18000},
				{0x07000000, 0x400},
			};
			static const struct { uint32_t base; uint32_t length; } rregions[] = {
				{0x02000000, 0x40000},
				{0x03000000, 0x8000},
				{0, 0}, {0, 0},
			};
			const void* chosen = ram ? (const void*) rregions : (const void*) vregions;
			const struct { uint32_t base; uint32_t length; }* regions = chosen;
			for (unsigned r = 0; r < 4 && regions[r].length; ++r) {
				for (uint32_t off = 0; off < regions[r].length; off += 2) {
					uint16_t value = (uint16_t) core->busRead16(core, regions[r].base + off);
					fputc(value & 0xFF, handle);
					fputc(value >> 8, handle);
				}
			}
			fclose(handle);
			printf("frame %u -> %s (vram)\n", frame, dumps[i].path);
		}
	}
	free(seen);

	free(buffer);
	mCoreConfigDeinit(&core->config);
	core->deinit(core);
	return status;
}

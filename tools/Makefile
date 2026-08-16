# Builds gbashot, the headless screenshot/replay harness, and gbawatch, the
# write-watchpoint tracer. Needs mgba and libpng from Homebrew:
# brew install mgba libpng
MGBA := $(shell brew --prefix mgba)
CFLAGS += -O2 -DUSE_PNG -I$(MGBA)/include $(shell pkg-config --cflags libpng)
LDFLAGS += -L$(MGBA)/lib -lmgba $(shell pkg-config --libs libpng) -lz

all: gbashot gbawatch

gbashot: gbashot.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

gbawatch: gbawatch.c
	$(CC) -O2 -I$(MGBA)/include -o $@ $< -L$(MGBA)/lib -lmgba

clean:
	rm -f gbashot gbawatch
.PHONY: all clean

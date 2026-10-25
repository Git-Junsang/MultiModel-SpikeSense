# 라즈베리파이 5(Cortex-A76)용 크로스 빌드. glibc 판이 달라도 돌게 정적 링크한다.
#   make            build/mmss_host (aarch64)
#   make check      qemu-aarch64로 verify_host.py 실행 (저장소 root에서 돈다)
#   make CC=gcc CFLAGS_ARCH=   x86 native 빌드(개발용)
CFLAGS_ARCH ?= -mcpu=cortex-a76
CFLAGS      = -O2 -Wall -Wextra -std=c11 $(CFLAGS_ARCH)
LDFLAGS     = -static -pthread -lm
SRC         = main.c mel.c ctl.c setup.c run.c

ifeq ($(origin CC),default)
CC = aarch64-linux-gnu-gcc-11
endif

build/mmss_host: $(SRC) host.h
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ $(SRC) $(LDFLAGS)

check: build/mmss_host
	cd ../.. && python3 software/host/verify_host.py

clean:
	rm -rf build

.PHONY: check clean

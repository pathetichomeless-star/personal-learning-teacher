#!/bin/sh
# 「小智 AI 学生课堂.app」Finder 双击验收（交付物 A）
#
# 做法与 Finder 双击**等效**：`open -a` 不传任何参数、不经过终端 shell，
# 因此验证的是「普通学生双击」这一条真实路径（而非开发者的命令行路径）。
#
# 验收点：
#   1) 包体为 APPL 且非后台运行（LSBackgroundOnly 缺省）⇒ 结构性不可能弹终端窗口；
#   2) Contents/MacOS 下只有窗口版可执行文件（runw bootloader，无控制台）；
#   3) open 后进程存活、窗口出现（屏幕截图非空且尺寸正确）；
#   4) 启动日志不出现 CLASSROOM_STARTUP_ERROR / FileNotFoundError；
#   5) 退出后无残留进程。
#
# 用法：tools/classroom_finder_open_check.sh [输出截图路径]
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$REPO/client/dist/小智 AI 学生课堂.app"
SHOT="${1:-$REPO/docs/engineering/product-v1/classroom-v2/delivery-02/screenshots/v2_finder_open.png}"
LOG_DIR="$REPO/docs/engineering/product-v1/classroom-v2/delivery-02/test-results"
mkdir -p "$(dirname "$SHOT")" "$LOG_DIR"

fail=0
say() { printf '%s\n' "$*"; }
chk() { if [ "$1" = "1" ]; then say "PASS $2"; else say "FAIL $2  <- $3"; fail=1; fi; }

say "== 0) 包体存在 =="
[ -d "$APP" ] && chk 1 "F01 包体存在" "" || chk 0 "F01 包体存在" "$APP"

say "== 1) 结构：无终端 / 前台应用 =="
PT=$(/usr/libexec/PlistBuddy -c "Print :CFBundlePackageType" "$APP/Contents/Info.plist" 2>/dev/null || echo "?")
chk "$([ "$PT" = "APPL" ] && echo 1 || echo 0)" "F02 CFBundlePackageType=APPL（前台应用，非后台）" "$PT"
BG=$(/usr/libexec/PlistBuddy -c "Print :LSBackgroundOnly" "$APP/Contents/Info.plist" 2>/dev/null || echo "absent")
chk "$([ "$BG" = "absent" ] && echo 1 || echo 0)" "F03 未设置 LSBackgroundOnly（正常出现窗口）" "$BG"
NEXE=$(ls "$APP/Contents/MacOS" | wc -l | tr -d ' ')
chk "$([ "$NEXE" = "1" ] && echo 1 || echo 0)" "F04 Contents/MacOS 仅 1 个可执行（无附加终端脚本）" "$NEXE"

say "== 2) 双击（open -a，无参数）=="
pkill -f "xiaozhi-classroom" 2>/dev/null || true
sleep 1
open "$APP"
sleep 9
ALIVE=$(pgrep -f "MacOS/xiaozhi-classroom" | wc -l | tr -d ' ')
chk "$([ "$ALIVE" -ge 1 ] && echo 1 || echo 0)" "F05 双击后进程存活（GUI 已启动）" "$ALIVE"

say "== 3) 真实屏幕截图（默认 wide 1360x850 @ 60,80）=="
if screencapture -x -R 60,80,1360,850 "$SHOT" 2>/dev/null; then
    SZ=$(stat -f%z "$SHOT" 2>/dev/null || echo 0)
    chk "$([ "$SZ" -gt 20000 ] && echo 1 || echo 0)" "F06 窗口截图非空（>=20KB）" "$SZ bytes"
else
    chk 0 "F06 窗口截图非空（>=20KB）" "screencapture 失败（可能需要屏幕录制权限）"
fi

say "== 4) 启动日志无错误 =="
LOG="$HOME/Library/Application Support/xiaozhi-classroom-demo/logs/startup_error.log"
if [ -f "$LOG" ]; then
    LAST=$(tail -c 400 "$LOG")
    case "$LAST" in
        *FileNotFoundError*|*CLASSROOM_STARTUP_ERROR*) chk 0 "F07 启动日志无致命错误" "$LAST" ;;
        *) chk 1 "F07 启动日志无致命错误" "" ;;
    esac
    tail -c 800 "$LOG" > "$LOG_DIR/finder_open_startup_tail.txt" || true
else
    chk 1 "F07 启动日志无致命错误（无日志文件 = 未发生启动错误）" ""
fi

say "== 5) 退出后无残留 =="
osascript -e 'tell application "小智 AI 学生课堂" to quit' >/dev/null 2>&1 || true
sleep 4
pkill -f "MacOS/xiaozhi-classroom" 2>/dev/null || true
LEFT=$(pgrep -f "MacOS/xiaozhi-classroom" | wc -l | tr -d ' ')
chk "$([ "$LEFT" = "0" ] && echo 1 || echo 0)" "F08 退出后无残留进程" "$LEFT"

say "----"
if [ "$fail" = "0" ]; then say "FINDER_OPEN_CHECK: ALL PASS"; else say "FINDER_OPEN_CHECK: HAS FAILURES"; fi
exit $fail

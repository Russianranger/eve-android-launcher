/* Original CI-only GDI child installed at the wrapper's fixed retail path.
 * This GUI-subsystem fixture starts minimized without activation. Direct launch
 * must exit 38; the unchanged production wrapper must restore/focus it and
 * forward exit 37. No game files, D3D driver, or user input are needed. */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

static unsigned int activation_messages, focus_messages;
static BOOL hung_message_pump;

static LRESULT CALLBACK window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_ACTIVATE && LOWORD(wparam) != WA_INACTIVE) activation_messages++;
    if (message == WM_SETFOCUS) focus_messages++;
    if (message == WM_PAINT) {
        PAINTSTRUCT paint;
        HDC dc = BeginPaint(hwnd, &paint);
        RECT rect;
        HBRUSH brush = CreateSolidBrush(RGB(32, 160, 224));
        GetClientRect(hwnd, &rect);
        FillRect(dc, &rect, brush);
        DeleteObject(brush);
        EndPaint(hwnd, &paint);
        return 0;
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}

static BOOL own_window(HWND hwnd)
{
    DWORD pid = 0;
    return hwnd && GetWindowThreadProcessId(hwnd, &pid) && pid == GetCurrentProcessId();
}

static void unix_identity(unsigned long *pid, unsigned long *parent, unsigned long *group, unsigned long *session)
{
    char data[2048], *fields;
    DWORD read = 0;
    HANDLE file = CreateFileW(L"Z:\\proc\\self\\stat", GENERIC_READ, FILE_SHARE_READ,
                              NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    *pid = *parent = *group = *session = 0;
    if (file == INVALID_HANDLE_VALUE) return;
    if (ReadFile(file, data, sizeof(data)-1, &read, NULL) && read) {
        char state;
        data[read] = 0;
        *pid = strtoul(data, NULL, 10);
        fields = strrchr(data, ')');
        if (!fields || sscanf(fields + 1, " %c %lu %lu %lu", &state, parent, group, session) != 4)
            *pid = *parent = *group = *session = 0;
    }
    CloseHandle(file);
}

static void report(BOOL passed, BOOL restored, BOOL foreground, BOOL focused,
                   BOOL hidden_untouched, BOOL popup_untouched, BOOL tool_untouched, DWORD exit_code)
{
    char json[1024];
    unsigned long pid, parent, group, session;
    DWORD written;
    HANDLE file;
    int length;
    unix_identity(&pid, &parent, &group, &session);
    length = snprintf(json, sizeof(json),
        "{\"format\":1,\"helper\":\"eve-client-window-fixture-1\",\"passed\":%s,"
        "\"windowsPid\":%lu,\"unixPid\":%lu,\"unixParent\":%lu,\"unixGroup\":%lu,\"unixSession\":%lu,"
        "\"restored\":%s,\"foregroundOwned\":%s,\"focusOwned\":%s,\"activationMessages\":%u,"
        "\"focusMessages\":%u,\"hiddenUntouched\":%s,\"ownedPopupUntouched\":%s,"
        "\"toolWindowUntouched\":%s,\"hungMessagePump\":%s,\"exitCode\":%lu}\n",
        passed ? "true" : "false", (unsigned long)GetCurrentProcessId(), pid, parent, group, session,
        restored ? "true" : "false", foreground ? "true" : "false", focused ? "true" : "false",
        activation_messages, focus_messages, hidden_untouched ? "true" : "false",
        popup_untouched ? "true" : "false", tool_untouched ? "true" : "false",
        hung_message_pump ? "true" : "false", (unsigned long)exit_code);
    if (length <= 0 || (size_t)length >= sizeof(json)) ExitProcess(40);
    file = CreateFileW(L"Z:\\client-state\\run\\client-window-fixture.json", GENERIC_WRITE,
                       FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE || !WriteFile(file, json, (DWORD)length, &written, NULL) ||
        written != (DWORD)length || !FlushFileBuffers(file)) ExitProcess(40);
    CloseHandle(file);
    fputs(json, stdout);
    fflush(stdout);
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, WCHAR *command_line, int show)
{
    WNDCLASSW window_class = {0};
    WCHAR cwd[MAX_PATH], hung_value[2];
    WCHAR **argv;
    int argc;
    HWND main_window, hidden, owned_popup, tool_window;
    MSG message;
    ULONGLONG started, focused_at = 0;
    BOOL restored = FALSE, foreground = FALSE, focused = FALSE, passed = FALSE;
    DWORD exit_code = 38;
    (void)previous; (void)command_line; (void)show;
    argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv || argc != 4 || wcscmp(argv[1], L"/noCrashReportUpload") ||
        wcscmp(argv[2], L"/resfileserver=http://127.0.0.1:26002/resfiles/") ||
        wcscmp(argv[3], L"/port:26000") || !GetCurrentDirectoryW(MAX_PATH, cwd) ||
        lstrcmpiW(cwd, L"Z:\\client\\tq")) ExitProcess(39);
    LocalFree(argv);
    SetProcessDPIAware();
    window_class.lpfnWndProc = window_proc;
    window_class.hInstance = instance;
    window_class.lpszClassName = L"EveClientWindowFixture";
    if (!RegisterClassW(&window_class)) ExitProcess(40);
    hidden = CreateWindowExW(0, window_class.lpszClassName, L"", WS_OVERLAPPEDWINDOW,
                             0, 0, 900, 700, NULL, NULL, instance, NULL);
    main_window = CreateWindowExW(0, window_class.lpszClassName, L"", WS_OVERLAPPEDWINDOW,
                                  32, 32, 240, 160, NULL, NULL, instance, NULL);
    owned_popup = CreateWindowExW(0,
        window_class.lpszClassName, L"", WS_POPUP,
        8, 8, 280, 200, main_window, NULL, instance, NULL);
    tool_window = CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        window_class.lpszClassName, L"", WS_POPUP,
        0, 0, 800, 600, NULL, NULL, instance, NULL);
    if (!hidden || !main_window || !owned_popup || !tool_window) ExitProcess(40);
    ShowWindow(tool_window, SW_SHOWNOACTIVATE);
    ShowWindow(owned_popup, SW_SHOWNOACTIVATE);
    ShowWindow(main_window, SW_SHOWMINNOACTIVE);
    hung_message_pump = GetEnvironmentVariableW(L"EVE_WINDOW_FIXTURE_HUNG", hung_value, 2) == 1 && hung_value[0] == L'1';
    if (hung_message_pump) {
        GUITHREADINFO info = {0};
        /* Deliberately never pump messages after creating the minimized child.
         * The production helper must not block in restore/raise/focus/probes,
         * and must still forward our distinctive exit after this finite sleep. */
        Sleep(10000);
        restored = !IsIconic(main_window) && IsWindowVisible(main_window);
        foreground = GetForegroundWindow() == main_window;
        info.cbSize = sizeof(info);
        focused = GetGUIThreadInfo(GetCurrentThreadId(), &info) && own_window(info.hwndFocus) &&
                  GetAncestor(info.hwndFocus, GA_ROOT) == main_window;
        report(FALSE, restored, foreground, focused, !IsWindowVisible(hidden),
               IsWindowEnabled(owned_popup) && GetWindow(owned_popup, GW_OWNER) == main_window,
               IsWindowVisible(tool_window) && (GetWindowLongPtrW(tool_window, GWL_EXSTYLE) & WS_EX_NOACTIVATE), 37);
        /* Avoid DestroyWindow or any message drain before reporting child exit. */
        ExitProcess(37);
    }
    started = GetTickCount64();
    while (GetTickCount64() - started < 12000) {
        GUITHREADINFO info = {0};
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
        restored = !IsIconic(main_window) && IsWindowVisible(main_window);
        foreground = GetForegroundWindow() == main_window;
        info.cbSize = sizeof(info);
        focused = GetGUIThreadInfo(GetCurrentThreadId(), &info) && own_window(info.hwndFocus) &&
                  GetAncestor(info.hwndFocus, GA_ROOT) == main_window;
        if (restored && foreground && focused && activation_messages && focus_messages) {
            if (!focused_at) focused_at = GetTickCount64();
            /* Keep the actual native child observable for /proc ownership proof. */
            if (GetTickCount64() - focused_at >= 3000) { passed = TRUE; exit_code = 37; break; }
        } else focused_at = 0;
        MsgWaitForMultipleObjectsEx(0, NULL, 25, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
    }
    passed = passed && !IsWindowVisible(hidden) && IsWindowEnabled(owned_popup) &&
             GetWindow(owned_popup, GW_OWNER) == main_window;
    if (!passed) exit_code = 38;
    report(passed, restored, foreground, focused, !IsWindowVisible(hidden),
           IsWindowEnabled(owned_popup) && GetWindow(owned_popup, GW_OWNER) == main_window,
           IsWindowVisible(tool_window) && (GetWindowLongPtrW(tool_window, GWL_EXSTYLE) & WS_EX_NOACTIVATE), exit_code);
    DestroyWindow(tool_window);
    DestroyWindow(owned_popup);
    DestroyWindow(hidden);
    DestroyWindow(main_window);
    ExitProcess(exit_code);
    return 40;
}

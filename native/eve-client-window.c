/*
 * Original fixed-target EVE launcher and bounded, numeric window observation.
 * The child inherits this console/process group. No user settings, titles,
 * class names, input, pixels, or arbitrary executable arguments are read.
 */
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
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define OBSERVE_MS 180000u
#define POLL_MS 1000u
#define PUBLISH_MS 5000u
#define WINDOW_LIMIT 256u
#define RECEIPT L"Z:\\client-state\\run\\client-window.json"
#define TEMP_RECEIPT L"Z:\\client-state\\run\\client-window.json.tmp"

typedef struct {
    HANDLE child;
    DWORD pid, thread, scanned, windows, visible, unowned, iconic;
    HWND selected;
    ULONGLONG area;
    BOOL truncated, selected_visible, selected_iconic, foreground_owned, focus_owned;
    BOOL gui_info, focus_attempted, focus_requested, focus_call_succeeded, focus_succeeded;
    BOOL restore_queued, raise_queued, observation_complete, window_observed;
    HWND attempt_window;
    ULONGLONG attempt_ms;
    RECT rect;
    BOOL rect_valid;
    int responsive;
    DWORD probe_error;
} OBSERVATION;

static const char *json_bool(BOOL value) { return value ? "true" : "false"; }

static BOOL child_alive(const OBSERVATION *state)
{
    /* STILL_ACTIVE is also a legal exit code; the process handle is decisive. */
    return WaitForSingleObject(state->child, 0) == WAIT_TIMEOUT;
}

static BOOL owned_window(HWND hwnd, const OBSERVATION *state)
{
    DWORD pid = 0;
    return hwnd && child_alive(state) && GetWindowThreadProcessId(hwnd, &pid) && pid == state->pid;
}

static BOOL CALLBACK inspect_window(HWND hwnd, LPARAM parameter)
{
    OBSERVATION *state = (OBSERVATION *)parameter;
    DWORD pid = 0, thread;
    RECT client, rect;
    ULONGLONG area;
    BOOL visible, iconic;
    if (++state->scanned > WINDOW_LIMIT) {
        state->truncated = TRUE;
        return FALSE;
    }
    thread = GetWindowThreadProcessId(hwnd, &pid);
    if (!thread || pid != state->pid) return TRUE;
    state->windows++;
    visible = IsWindowVisible(hwnd);
    iconic = IsIconic(hwnd);
    state->visible += !!visible;
    state->iconic += !!iconic;
    if (GetWindow(hwnd, GW_OWNER)) return TRUE;
    state->unowned++;
    if (!visible || !IsWindowEnabled(hwnd) ||
        (GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)) ||
        !GetWindowRect(hwnd, &rect)) return TRUE;
    if (!GetClientRect(hwnd, &client)) client = rect;
    if (client.right <= client.left || client.bottom <= client.top) client = rect;
    if (client.right <= client.left || client.bottom <= client.top) return TRUE;
    area = (ULONGLONG)((LONGLONG)client.right - client.left) *
           (ULONGLONG)((LONGLONG)client.bottom - client.top);
    if (!state->selected || area > state->area) {
        state->selected = hwnd;
        state->thread = thread;
        state->area = area;
        state->selected_visible = visible;
        state->selected_iconic = iconic;
        state->rect = rect;
        state->rect_valid = TRUE;
    }
    return TRUE;
}

static void observe(OBSERVATION *state, ULONGLONG elapsed)
{
    GUITHREADINFO info = {0};
    DWORD_PTR result = 0;
    state->scanned = state->windows = state->visible = state->unowned = state->iconic = 0;
    state->selected = NULL;
    state->thread = 0;
    state->area = 0;
    state->truncated = state->selected_visible = state->selected_iconic = FALSE;
    state->rect_valid = state->gui_info = state->foreground_owned = state->focus_owned = FALSE;
    state->responsive = -1;
    state->probe_error = 0;
    if (!child_alive(state)) return;
    EnumWindows(inspect_window, (LPARAM)state);
    if (state->selected && owned_window(state->selected, state)) {
        state->window_observed = TRUE;
        if (!state->focus_attempted && state->selected_visible &&
            !GetWindow(state->selected, GW_OWNER) && IsWindowEnabled(state->selected)) {
            state->focus_attempted = TRUE;
            state->attempt_window = state->selected;
            state->attempt_ms = elapsed;
            if (IsIconic(state->selected) && owned_window(state->selected, state))
                state->restore_queued = ShowWindowAsync(state->selected, SW_RESTORE);
        }
        /* Restore is queued on EVE's thread. Wait until its real state changes
         * before making the single foreground request, rather than racing it. */
        if (state->focus_attempted && !state->focus_requested &&
            state->selected == state->attempt_window && !IsIconic(state->selected) &&
            IsWindowVisible(state->selected) && IsWindowEnabled(state->selected) &&
            !GetWindow(state->selected, GW_OWNER) && owned_window(state->selected, state)) {
            state->focus_requested = TRUE;
            state->focus_call_succeeded = SetForegroundWindow(state->selected);
            /* BringWindowToTop synchronously calls a foreign window thread in
             * Wine. A hung game must never prevent this helper forwarding exit. */
            if (owned_window(state->selected, state))
                state->raise_queued = SetWindowPos(state->selected, HWND_TOP, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS);
        }
        if (owned_window(state->selected, state)) {
            SetLastError(ERROR_SUCCESS);
            state->responsive = !!SendMessageTimeoutW(state->selected, WM_NULL, 0, 0,
                SMTO_ABORTIFHUNG | SMTO_BLOCK | SMTO_ERRORONEXIT, 50, &result);
            if (!state->responsive) state->probe_error = GetLastError();
        }
        state->selected_iconic = IsIconic(state->selected);
        state->rect_valid = GetWindowRect(state->selected, &state->rect);
        info.cbSize = sizeof(info);
        if (owned_window(state->selected, state)) {
            DWORD selected_pid;
            state->thread = GetWindowThreadProcessId(state->selected, &selected_pid);
            state->gui_info = selected_pid == state->pid && state->thread && GetGUIThreadInfo(state->thread, &info);
        }
        state->focus_owned = state->gui_info && owned_window(info.hwndFocus, state);
    }
    state->foreground_owned = owned_window(GetForegroundWindow(), state);
    /* Cross-thread activation is asynchronous. Verify real focus on subsequent
     * polls and retain that evidence even if the user later switches windows. */
    if (state->focus_requested && state->foreground_owned && state->focus_owned && !state->selected_iconic)
        state->focus_succeeded = TRUE;
}

static BOOL publish(const OBSERVATION *state, const char session[33], const char *phase,
                    ULONGLONG elapsed, BOOL exited, DWORD exit_code, DWORD error)
{
    char json[4096], exit_json[32], rect_json[160], responsive_json[8], attempt_json[32];
    HANDLE file;
    DWORD written = 0, write_error;
    int length;
    BOOL success;
    if (exited) snprintf(exit_json, sizeof(exit_json), "%lu", (unsigned long)exit_code);
    else strcpy(exit_json, "null");
    if (state->rect_valid) snprintf(rect_json, sizeof(rect_json),
        "{\"left\":%ld,\"top\":%ld,\"right\":%ld,\"bottom\":%ld}",
        (long)state->rect.left, (long)state->rect.top, (long)state->rect.right, (long)state->rect.bottom);
    else strcpy(rect_json, "null");
    strcpy(responsive_json, state->responsive < 0 ? "null" : json_bool(state->responsive));
    if (state->focus_attempted) snprintf(attempt_json, sizeof(attempt_json), "%llu",
        (unsigned long long)state->attempt_ms);
    else strcpy(attempt_json, "null");
    length = snprintf(json, sizeof(json),
        "{\"format\":1,\"helper\":\"eve-client-window-1\",\"session\":\"%s\",\"phase\":\"%s\","
        "\"wrapperWindowsPid\":%lu,\"childWindowsPid\":%lu,\"childExitCode\":%s,\"elapsedMs\":%llu,"
        "\"windowsOwned\":%lu,\"visibleWindows\":%lu,\"unownedWindows\":%lu,\"iconicWindows\":%lu,"
        "\"windowScanTruncated\":%s,\"selectedWindow\":%llu,\"windowThreadId\":%lu,"
        "\"windowVisible\":%s,\"windowIconic\":%s,\"foregroundOwned\":%s,\"focusOwned\":%s,"
        "\"guiInfoAvailable\":%s,\"focusAttempted\":%s,\"focusCallSucceeded\":%s,\"focusSucceeded\":%s,"
        "\"focusAttemptWindow\":%llu,\"focusAttemptElapsedMs\":%s,\"restoreQueued\":%s,\"raiseQueued\":%s,"
        "\"responsive\":%s,\"probeTimeoutMs\":50,\"probeWin32Error\":%lu,\"rect\":%s,\"observationComplete\":%s,\"win32Error\":%lu}\n",
        session, phase, (unsigned long)GetCurrentProcessId(), (unsigned long)state->pid, exit_json,
        (unsigned long long)elapsed, (unsigned long)state->windows, (unsigned long)state->visible,
        (unsigned long)state->unowned, (unsigned long)state->iconic, json_bool(state->truncated),
        (unsigned long long)(uintptr_t)state->selected, (unsigned long)state->thread,
        json_bool(state->selected_visible), json_bool(state->selected_iconic), json_bool(state->foreground_owned),
        json_bool(state->focus_owned), json_bool(state->gui_info), json_bool(state->focus_attempted),
        json_bool(state->focus_call_succeeded), json_bool(state->focus_succeeded),
        (unsigned long long)(uintptr_t)state->attempt_window, attempt_json, json_bool(state->restore_queued),
        json_bool(state->raise_queued), responsive_json, (unsigned long)state->probe_error, rect_json,
        json_bool(state->observation_complete), (unsigned long)error);
    if (length <= 0 || (size_t)length >= sizeof(json)) return FALSE;
    file = CreateFileW(TEMP_RECEIPT, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    success = file != INVALID_HANDLE_VALUE;
    if (success) {
        success = WriteFile(file, json, (DWORD)length, &written, NULL) && written == (DWORD)length && FlushFileBuffers(file);
        write_error = GetLastError();
        if (!CloseHandle(file)) { success = FALSE; write_error = GetLastError(); }
        if (success) success = MoveFileExW(TEMP_RECEIPT, RECEIPT, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
        else SetLastError(write_error);
    }
    write_error = success ? ERROR_SUCCESS : GetLastError();
    fputs(json, stdout);
    fflush(stdout);
    if (!success) fprintf(stderr, "{\"helper\":\"eve-client-window-write-1\",\"win32Error\":%lu}\n", (unsigned long)write_error);
    return success;
}

static void pump_messages(void)
{
    MSG message;
    unsigned int count = 0;
    /* A flooded queue must not indefinitely postpone child-exit/deadline checks. */
    while (count++ < 256 && PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
}

int wmain(int argc, WCHAR **argv)
{
    static const WCHAR executable[] = L"Z:\\client\\tq\\bin64\\exefile.exe";
    WCHAR command[] = L"\"Z:\\client\\tq\\bin64\\exefile.exe\" /noCrashReportUpload "
        L"/resfileserver=http://127.0.0.1:26002/resfiles/ /port:26000";
    WCHAR nonce[34];
    char session[33] = {0};
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    OBSERVATION state = {0};
    DWORD nonce_length, error = 0, exit_code = 1, wait;
    DWORD std_flags[3] = {0};
    HANDLE std_handles[3];
    ULONGLONG started = GetTickCount64(), last_poll, last_publish;
    unsigned int index;
    BOOL previously_observed = FALSE, previously_focused = FALSE;
    (void)argv;
    state.responsive = -1;
    nonce_length = GetEnvironmentVariableW(L"EVE_WINDOW_SESSION", nonce, sizeof(nonce) / sizeof(nonce[0]));
    if (argc != 1 || nonce_length != 32) error = ERROR_INVALID_PARAMETER;
    for (index = 0; !error && index < 32; index++) {
        WCHAR ch = nonce[index];
        if (!((ch >= L'0' && ch <= L'9') || (ch >= L'a' && ch <= L'f') || (ch >= L'A' && ch <= L'F')))
            error = ERROR_INVALID_PARAMETER;
        else session[index] = (char)ch;
    }
    if (error) {
        /* An invalid nonce is never copied into output. */
        memset(session, '0', 32);
        publish(&state, session, "failed", 0, FALSE, 0, error);
        return 1;
    }
    SetProcessDPIAware();
    pump_messages();
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = std_handles[0] = GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput = std_handles[1] = GetStdHandle(STD_OUTPUT_HANDLE);
    startup.hStdError = std_handles[2] = GetStdHandle(STD_ERROR_HANDLE);
    /* Only controlled Runtime stdio handles are open before CreateProcess.
     * Explicit inheritance keeps the child's stdout/stderr in its log pipe. */
    for (index = 0; index < 3; index++) {
        if (!std_handles[index] || std_handles[index] == INVALID_HANDLE_VALUE ||
            !GetHandleInformation(std_handles[index], &std_flags[index])) {
            error = GetLastError();
            if (!error) error = ERROR_INVALID_HANDLE;
            publish(&state, session, "failed", GetTickCount64() - started, FALSE, 0, error);
            return 111;
        }
    }
    for (index = 0; index < 3; index++) {
        if (!SetHandleInformation(std_handles[index], HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT)) {
            error = GetLastError();
            publish(&state, session, "failed", GetTickCount64() - started, FALSE, 0, error);
            return 111;
        }
    }
    /* A CUI wrapper and flags=0 preserve the inherited console. Wine calls
     * setsid for detached/new-console children, losing Runtime's owned group. */
    if (!CreateProcessW(executable, command, NULL, NULL, TRUE, 0, NULL,
                        L"Z:\\client\\tq", &startup, &process)) {
        error = GetLastError();
        publish(&state, session, "failed", GetTickCount64() - started, FALSE, 0, error);
        return 111;
    }
    for (index = 0; index < 3; index++)
        SetHandleInformation(std_handles[index], HANDLE_FLAG_INHERIT, std_flags[index] & HANDLE_FLAG_INHERIT);
    CloseHandle(process.hThread);
    state.child = process.hProcess;
    state.pid = process.dwProcessId;
    publish(&state, session, "child_created", GetTickCount64() - started, FALSE, 0, 0);
    last_poll = GetTickCount64() - POLL_MS;
    last_publish = GetTickCount64();
    for (;;) {
        ULONGLONG now = GetTickCount64(), elapsed = now - started;
        wait = WaitForSingleObject(state.child, 0);
        if (wait == WAIT_OBJECT_0) {
            if (!GetExitCodeProcess(state.child, &exit_code)) {
                error = GetLastError();
                publish(&state, session, "failed", elapsed, FALSE, 0, error);
                exit_code = 1;
            } else publish(&state, session, "child_exited", elapsed, TRUE, exit_code, 0);
            break;
        }
        if (wait == WAIT_FAILED) {
            error = GetLastError();
            publish(&state, session, "failed", elapsed, FALSE, 0, error);
            exit_code = 1;
            break;
        }
        if (!state.observation_complete && elapsed >= OBSERVE_MS) {
            state.observation_complete = TRUE;
            publish(&state, session, state.window_observed ? "window_observed" : "child_created", elapsed, FALSE, 0, 0);
            last_publish = now;
        } else if (!state.observation_complete && now - last_poll >= POLL_MS) {
            observe(&state, elapsed);
            last_poll = now;
            if (now - last_publish >= PUBLISH_MS || state.window_observed != previously_observed ||
                state.focus_succeeded != previously_focused) {
                publish(&state, session, state.window_observed ? "window_observed" : "child_created", elapsed, FALSE, 0, 0);
                last_publish = now;
            }
            previously_observed = state.window_observed;
            previously_focused = state.focus_succeeded;
        }
        wait = MsgWaitForMultipleObjectsEx(1, &state.child, state.observation_complete ? INFINITE : 100,
                                          QS_ALLINPUT, MWMO_INPUTAVAILABLE);
        if (wait == WAIT_FAILED) {
            /* The valid child handle still governs lifetime if GUI waiting
             * fails. Avoid an orphan or a busy loop while Runtime can stop us. */
            Sleep(100);
        }
        pump_messages();
    }
    CloseHandle(state.child);
    /* Preserve all DWORD values, including 259 and values above INT_MAX. */
    ExitProcess(exit_code);
    return 1;
}

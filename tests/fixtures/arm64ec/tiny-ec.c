#include <windows.h>
__declspec(dllexport) int original_ec_add(int a, int b) { return a + b; }
BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID reserved) {
    (void)module; (void)reason; (void)reserved; return TRUE;
}

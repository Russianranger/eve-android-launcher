/* Original launcher device/swapchain probe. Does not read CCP client files. */
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <dxgi.h>
#include <stdio.h>
#include <string.h>

typedef HRESULT (WINAPI *CreateDeviceAndSwapChain)(IDXGIAdapter *, D3D_DRIVER_TYPE,
    HMODULE, UINT, const D3D_FEATURE_LEVEL *, UINT, UINT,
    const DXGI_SWAP_CHAIN_DESC *, IDXGISwapChain **, ID3D11Device **,
    D3D_FEATURE_LEVEL *, ID3D11DeviceContext **);

int main(void)
{
    HWND window = NULL;
    HMODULE module = NULL;
    IDXGISwapChain *swapchain = NULL;
    ID3D11Device *device = NULL;
    ID3D11DeviceContext *context = NULL;
    ID3D11Texture2D *buffer = NULL;
    ID3D11RenderTargetView *target = NULL;
    int result = 1;
    HRESULT hr = E_FAIL;
    window = CreateWindowExW(0, L"STATIC", L"EVE renderer check", WS_OVERLAPPEDWINDOW,
                             0, 0, 64, 64, NULL, NULL, GetModuleHandleW(NULL), NULL);
    if (!window) goto done;
    ShowWindow(window, SW_SHOWNOACTIVATE);
    module = LoadLibraryW(L"d3d11.dll");
    if (!module) goto done;
    CreateDeviceAndSwapChain create;
    FARPROC address = GetProcAddress(module, "D3D11CreateDeviceAndSwapChain");
    if (!address) goto done;
    /* FARPROC and the function pointer have identical representation on x64. */
    memcpy(&create, &address, sizeof(create));
    DXGI_SWAP_CHAIN_DESC desc = {0};
    desc.BufferDesc.Width = 64;
    desc.BufferDesc.Height = 64;
    desc.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.SampleDesc.Count = 1;
    desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    desc.BufferCount = 2;
    desc.OutputWindow = window;
    desc.Windowed = TRUE;
    desc.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
    const D3D_FEATURE_LEVEL levels[] = {D3D_FEATURE_LEVEL_11_0};
    D3D_FEATURE_LEVEL level;
    hr = create(NULL, D3D_DRIVER_TYPE_HARDWARE, NULL, 0, levels, 1, D3D11_SDK_VERSION,
                &desc, &swapchain, &device, &level, &context);
    if (FAILED(hr) || level < D3D_FEATURE_LEVEL_11_0) goto done;
    hr = IDXGISwapChain_GetBuffer(swapchain, 0, &IID_ID3D11Texture2D, (void **)&buffer);
    if (FAILED(hr)) goto done;
    hr = ID3D11Device_CreateRenderTargetView(device, (ID3D11Resource *)buffer, NULL, &target);
    if (FAILED(hr)) goto done;
    const FLOAT clear[] = {0.02f, 0.04f, 0.06f, 1.0f};
    ID3D11DeviceContext_ClearRenderTargetView(context, target, clear);
    ID3D11DeviceContext_Flush(context);
    hr = IDXGISwapChain_Present(swapchain, 0, 0);
    if (FAILED(hr)) goto done;
    puts("EVE_DXVK_TURNIP_OK D3D11 device and X11 software swapchain presented");
    result = 0;
done:
    if (result) fprintf(stderr, "EVE_DXVK_TURNIP_FAILED hr=0x%08lx win32=%lu\n", (unsigned long)hr, (unsigned long)GetLastError());
    if (target) ID3D11RenderTargetView_Release(target);
    if (buffer) ID3D11Texture2D_Release(buffer);
    if (context) ID3D11DeviceContext_Release(context);
    if (device) ID3D11Device_Release(device);
    if (swapchain) IDXGISwapChain_Release(swapchain);
    if (module) FreeLibrary(module);
    if (window) DestroyWindow(window);
    return result;
}

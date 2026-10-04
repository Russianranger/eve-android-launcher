/* Original x64 -> native ARM64EC DXVK rendering qualification. No network or credentials. */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0601
#include <windows.h>
#include <wincrypt.h>
#include <d3d11.h>
#include <dxgi.h>
#include <d3dcompiler.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define PATH_CAP 2048
#define DLL_LIMIT (64u * 1024u * 1024u)
#define IMAGE_SIDE 128u
#define REQUESTED_SYNC_INTERVAL 1u
#define RELEASE(type, obj) do { if (obj) { type##_Release(obj); obj = NULL; } } while (0)
#define CHECK(call, name) do { stage = name; hr = (call); if (FAILED(hr)) goto cleanup; } while (0)
#define CHECK_OBJECT(call, object, name) do { CHECK(call, name); \
    if (!(object)) { hr = E_UNEXPECTED; goto cleanup; } } while (0)
#define FAIL_WIN32() do { win32_error = GetLastError(); \
    if (!win32_error) { win32_error = ERROR_INVALID_DATA; } \
    hr = HRESULT_FROM_WIN32(win32_error); goto cleanup; } while (0)

static const GUID factory1_iid = {0x770aae78,0xf26f,0x4dba,{0xa8,0x29,0x25,0x3c,0x83,0xd1,0xb3,0x87}};
static const GUID texture2d_iid = {0x6f15aaf2,0xd208,0x4e89,{0x9a,0xb4,0x48,0x95,0x35,0xd3,0x4f,0x9c}};

typedef HRESULT (WINAPI *create_factory_fn)(REFIID, void **);
typedef HRESULT (WINAPI *create_device_fn)(IDXGIAdapter *, D3D_DRIVER_TYPE, HMODULE, UINT,
    const D3D_FEATURE_LEVEL *, UINT, UINT, ID3D11Device **, D3D_FEATURE_LEVEL *, ID3D11DeviceContext **);
typedef HRESULT (WINAPI *compile_fn)(LPCVOID, SIZE_T, LPCSTR, const D3D_SHADER_MACRO *, ID3DInclude *,
    LPCSTR, LPCSTR, UINT, UINT, ID3DBlob **, ID3DBlob **);

struct module_info {
    WCHAR path[PATH_CAP];
    char sha256[65];
    WORD disk_machine;
    WORD loaded_machine;
    DWORD chpe_version;
    DWORD ec_range_count;
    BOOL identity_verified;
    const char *identity_error;
};

static DWORD read32(const BYTE *p) { DWORD n; memcpy(&n, p, sizeof(n)); return n; }
static WORD read16(const BYTE *p) { WORD n; memcpy(&n, p, sizeof(n)); return n; }
static ULONGLONG read64(const BYTE *p) { ULONGLONG n; memcpy(&n, p, sizeof(n)); return n; }
static BOOL has_bytes(size_t total, size_t offset, size_t length)
{
    return offset <= total && length <= total - offset;
}

/* All reads are bounded by the actual raw file. No trust in RVA/section counts. */
static const BYTE *raw_rva(const BYTE *data, size_t size, size_t nt, DWORD rva, size_t length)
{
    WORD sections, optional_size;
    size_t table, i;
    DWORD headers;
    if (!has_bytes(size, nt, 24)) return NULL;
    sections = read16(data + nt + 6);
    optional_size = read16(data + nt + 20);
    if (optional_size < 64 || !has_bytes(size, nt + 24, optional_size)) return NULL;
    headers = read32(data + nt + 24 + 60);
    if (rva < headers && length <= (size_t)headers - rva && has_bytes(size, rva, length))
        return data + rva;
    table = nt + 24 + optional_size;
    if (!has_bytes(size, table, (size_t)sections * 40)) return NULL;
    for (i = 0; i < sections; ++i) {
        const BYTE *section = data + table + i * 40;
        DWORD start = read32(section + 12), raw_size = read32(section + 16);
        DWORD raw_start = read32(section + 20);
        size_t delta;
        if (rva < start) continue;
        delta = (size_t)rva - start;
        if (delta > raw_size || length > (size_t)raw_size - delta) continue;
        if (!has_bytes(size, raw_start, delta) || !has_bytes(size, (size_t)raw_start + delta, length))
            return NULL;
        return data + raw_start + delta;
    }
    return NULL;
}

/* LLD coalesces consecutive ranges of one ISA across output sections. A
 * range can therefore include only the SectionAlignment gap between two
 * executable sections. Its endpoints and all actual code bytes still need
 * raw file backing; a range beginning or ending in padding is invalid. */
static BOOL executable_code_range(const BYTE *data, size_t size, size_t section_table,
    WORD sections, DWORD section_alignment, DWORD start, DWORD length)
{
    DWORD cursor = start, end = start + length, previous_end = 0;
    BOOL have_previous = FALSE;
    unsigned int index;
    for (index = 0; index < sections; ++index) {
        const BYTE *section = data + section_table + index * 40;
        DWORD virtual_start = read32(section + 12), virtual_size = read32(section + 8);
        DWORD section_end = virtual_start + virtual_size, segment_end, delta, piece;
        DWORD raw_size = read32(section + 16), raw_start = read32(section + 20);
        if (section_end <= cursor) continue;
        if (virtual_start > cursor) {
            ULONGLONG aligned = ((ULONGLONG)previous_end + section_alignment - 1u) &
                                ~((ULONGLONG)section_alignment - 1u);
            if (!have_previous || cursor != previous_end || aligned != virtual_start || end <= virtual_start)
                return FALSE;
            cursor = virtual_start;
        }
        if (!(read32(section + 36) & IMAGE_SCN_MEM_EXECUTE)) return FALSE;
        segment_end = end < section_end ? end : section_end;
        delta = cursor - virtual_start; piece = segment_end - cursor;
        if (delta > raw_size || piece > raw_size - delta ||
            !has_bytes(size, (size_t)raw_start + delta, piece)) return FALSE;
        cursor = segment_end;
        if (cursor == end) return TRUE;
        previous_end = section_end; have_previous = TRUE;
    }
    return FALSE;
}

static BOOL arm64ec_file(const BYTE *data, size_t size, struct module_info *info)
{
    size_t nt, optional, section_table;
    WORD optional_size, sections;
    DWORD config_rva, config_size, metadata_rva, code_map, count, i, image_size, section_alignment;
    DWORD previous_section_end = 0, header_size;
    const BYTE *config, *metadata, *ranges;
    ULONGLONG image_base, metadata_va;
    if (!has_bytes(size, 0, 64) || read16(data) != IMAGE_DOS_SIGNATURE) return FALSE;
    nt = read32(data + 60);
    if (!has_bytes(size, nt, 24) || read32(data + nt) != IMAGE_NT_SIGNATURE) return FALSE;
    info->disk_machine = read16(data + nt + 4);
    optional_size = read16(data + nt + 20);
    sections = read16(data + nt + 6);
    optional = nt + 24;
    if (info->disk_machine != IMAGE_FILE_MACHINE_AMD64 || optional_size < 208 ||
        !has_bytes(size, optional, optional_size) || read16(data + optional) != IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
        read32(data + optional + 108) <= IMAGE_DIRECTORY_ENTRY_LOAD_CONFIG) return FALSE;
    image_size = read32(data + optional + 56);
    header_size = read32(data + optional + 60);
    section_alignment = read32(data + optional + 32);
    if (!section_alignment || section_alignment > 0x100000u ||
        (section_alignment & (section_alignment - 1u))) return FALSE;
    section_table = optional + optional_size;
    if (sections > 96 || !has_bytes(size, section_table, (size_t)sections * 40)) return FALSE;
    for (i = 0; i < sections; ++i) {
        const BYTE *section = data + section_table + i * 40;
        DWORD raw_size = read32(section + 16), raw_start = read32(section + 20);
        DWORD virtual_start = read32(section + 12), virtual_size = read32(section + 8);
        if (!has_bytes(size, raw_start, raw_size)) return FALSE;
        if ((virtual_size && virtual_start < header_size) ||
            virtual_start % section_alignment || virtual_start < previous_section_end ||
            virtual_start > image_size || virtual_size > image_size - virtual_start) return FALSE;
        previous_section_end = virtual_start + virtual_size;
    }
    image_base = read64(data + optional + 24);
    config_rva = read32(data + optional + 112 + IMAGE_DIRECTORY_ENTRY_LOAD_CONFIG * 8);
    config_size = read32(data + optional + 116 + IMAGE_DIRECTORY_ENTRY_LOAD_CONFIG * 8);
    if (!config_rva || config_size < 208 || !(config = raw_rva(data, size, nt, config_rva, 208)) ||
        read32(config) < 208) return FALSE;
    metadata_va = read64(config + 200); /* IMAGE_LOAD_CONFIG_DIRECTORY64.CHPEMetadataPointer */
    if (metadata_va < image_base || metadata_va - image_base > 0xffffffffu) return FALSE;
    metadata_rva = (DWORD)(metadata_va - image_base);
    if (!metadata_rva || !(metadata = raw_rva(data, size, nt, metadata_rva, 12))) return FALSE;
    info->chpe_version = read32(metadata);
    code_map = read32(metadata + 4);
    count = read32(metadata + 8);
    if (!info->chpe_version || !code_map || !count || count > 65536u ||
        !(ranges = raw_rva(data, size, nt, code_map, (size_t)count * 8))) return FALSE;
    for (i = 0; i < count; ++i) {
        DWORD start = read32(ranges + i * 8), length = read32(ranges + i * 8 + 4);
        DWORD code_start = start & ~3u;
        if (!length || (start & 3u) == 3u) return FALSE;
        if (code_start >= image_size || length > image_size - code_start) return FALSE;
        if (!executable_code_range(data, size, section_table, sections,
                section_alignment, code_start, length)) return FALSE;
        if ((start & 3u) == 1u) ++info->ec_range_count; /* Wine 10.13 native ARM64EC tag */
    }
    return info->ec_range_count != 0;
}

static BOOL expected_digest(const WCHAR *value, char output[65])
{
    unsigned int i;
    if (wcslen(value) != 64) return FALSE;
    for (i = 0; i < 64; ++i) {
        WCHAR c = value[i];
        if (c >= L'A' && c <= L'F') c += L'a' - L'A';
        if (!((c >= L'0' && c <= L'9') || (c >= L'a' && c <= L'f'))) return FALSE;
        output[i] = (char)c;
    }
    output[64] = 0;
    return TRUE;
}

static BOOL qualify_module(HMODULE module, const WCHAR *expected_path, const WCHAR *digest,
                           struct module_info *info)
{
    HANDLE file = INVALID_HANDLE_VALUE, mapping = NULL;
    HCRYPTPROV provider = 0;
    HCRYPTHASH hash = 0;
    BYTE buffer[65536], sha[32];
    const BYTE *data = NULL;
    LARGE_INTEGER size;
    ULONGLONG total_read = 0;
    DWORD bytes, hash_length = sizeof(sha), path_length, saved_error = ERROR_INVALID_DATA;
    WCHAR full_expected[PATH_CAP], full_actual[PATH_CAP];
    char expected[65];
    BOOL success = FALSE;
    unsigned int i;
    const IMAGE_DOS_HEADER *dos;
    const IMAGE_NT_HEADERS64 *nt;
    MEMORY_BASIC_INFORMATION header_region = {0};
#define IDENTITY_API_FAIL(reason) do { info->identity_error = reason; saved_error = GetLastError(); \
    if (!saved_error) { saved_error = ERROR_INVALID_DATA; } goto cleanup; } while (0)
#define IDENTITY_LOGIC_FAIL(reason) do { info->identity_error = reason; \
    saved_error = ERROR_INVALID_DATA; goto cleanup; } while (0)
    path_length = GetModuleFileNameW(module, info->path, PATH_CAP);
    info->path[PATH_CAP - 1] = 0;
    if (!path_length) IDENTITY_API_FAIL("get_loaded_module_path");
    if (path_length >= PATH_CAP) IDENTITY_LOGIC_FAIL("loaded_module_path_too_long");
    if (!expected_digest(digest, expected)) IDENTITY_LOGIC_FAIL("expected_hash_invalid");
    path_length = GetFullPathNameW(expected_path, PATH_CAP, full_expected, NULL);
    if (!path_length) IDENTITY_API_FAIL("normalize_expected_path");
    if (path_length >= PATH_CAP) IDENTITY_LOGIC_FAIL("expected_module_path_too_long");
    path_length = GetFullPathNameW(info->path, PATH_CAP, full_actual, NULL);
    if (!path_length) IDENTITY_API_FAIL("normalize_loaded_path");
    if (path_length >= PATH_CAP) IDENTITY_LOGIC_FAIL("loaded_module_path_too_long");
    if (_wcsicmp(full_expected, full_actual)) IDENTITY_LOGIC_FAIL("loaded_module_path_mismatch");
    if (VirtualQuery(module, &header_region, sizeof(header_region)) != sizeof(header_region))
        IDENTITY_API_FAIL("query_loaded_header");
    if (header_region.State != MEM_COMMIT || header_region.RegionSize < sizeof(IMAGE_DOS_HEADER) ||
        (header_region.Protect & (PAGE_NOACCESS | PAGE_GUARD))) IDENTITY_LOGIC_FAIL("loaded_header_unreadable");
    dos = (const IMAGE_DOS_HEADER *)module;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0 || dos->e_lfanew > 65536)
        IDENTITY_LOGIC_FAIL("loaded_dos_header_invalid");
    if (!has_bytes(header_region.RegionSize, (size_t)dos->e_lfanew, sizeof(IMAGE_NT_HEADERS64)))
        IDENTITY_LOGIC_FAIL("loaded_pe_header_out_of_bounds");
    nt = (const IMAGE_NT_HEADERS64 *)((const BYTE *)module + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) IDENTITY_LOGIC_FAIL("loaded_pe_header_invalid");
    info->loaded_machine = nt->FileHeader.Machine;
    file = CreateFileW(info->path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                       FILE_FLAG_SEQUENTIAL_SCAN, NULL);
    if (file == INVALID_HANDLE_VALUE) IDENTITY_API_FAIL("open_loaded_module_file");
    if (!GetFileSizeEx(file, &size)) IDENTITY_API_FAIL("get_loaded_module_file_size");
    if (size.QuadPart <= 0 || size.QuadPart > DLL_LIMIT) IDENTITY_LOGIC_FAIL("loaded_module_file_size_invalid");
    if (!CryptAcquireContextW(&provider, NULL, NULL, PROV_RSA_AES, CRYPT_VERIFYCONTEXT))
        IDENTITY_API_FAIL("initialize_hash_provider");
    if (!CryptCreateHash(provider, CALG_SHA_256, 0, 0, &hash)) IDENTITY_API_FAIL("initialize_sha256");
    for (;;) {
        if (!ReadFile(file, buffer, sizeof(buffer), &bytes, NULL)) IDENTITY_API_FAIL("read_loaded_module_file");
        if (!bytes) break;
        total_read += bytes;
        if (total_read > (ULONGLONG)size.QuadPart) IDENTITY_LOGIC_FAIL("loaded_module_file_changed");
        if (!CryptHashData(hash, buffer, bytes, 0)) IDENTITY_API_FAIL("hash_loaded_module_file");
    }
    if (total_read != (ULONGLONG)size.QuadPart) IDENTITY_LOGIC_FAIL("loaded_module_file_changed");
    if (!CryptGetHashParam(hash, HP_HASHVAL, sha, &hash_length, 0)) IDENTITY_API_FAIL("read_loaded_module_hash");
    if (hash_length != sizeof(sha)) IDENTITY_LOGIC_FAIL("loaded_module_hash_size_invalid");
    for (i = 0; i < sizeof(sha); ++i) sprintf(info->sha256 + i * 2, "%02x", sha[i]);
    info->sha256[64] = 0;
    if (strcmp(info->sha256, expected)) IDENTITY_LOGIC_FAIL("loaded_module_hash_mismatch");
    mapping = CreateFileMappingW(file, NULL, PAGE_READONLY, 0, 0, NULL);
    if (!mapping) IDENTITY_API_FAIL("map_loaded_module_file");
    data = (const BYTE *)MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0);
    if (!data) IDENTITY_API_FAIL("read_loaded_module_mapping");
    if (!arm64ec_file(data, (size_t)size.QuadPart, info)) IDENTITY_LOGIC_FAIL("loaded_module_not_native_arm64ec");
    success = info->identity_verified = TRUE;
cleanup:
    if (success) saved_error = ERROR_SUCCESS;
    if (data) UnmapViewOfFile(data);
    if (mapping) CloseHandle(mapping);
    if (hash) CryptDestroyHash(hash);
    if (provider) CryptReleaseContext(provider, 0);
    if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
    SetLastError(saved_error);
    return success;
#undef IDENTITY_API_FAIL
#undef IDENTITY_LOGIC_FAIL
}

static void json_ascii(const char *text)
{
    const unsigned char *p = (const unsigned char *)text;
    putchar('"');
    for (; *p; ++p) {
        if (*p == '"' || *p == '\\') printf("\\%c", *p);
        else if (*p < 32 || *p >= 127) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}
static void json_wide(const WCHAR *text)
{
    putchar('"');
    for (; *text; ++text) {
        if (*text == L'"' || *text == L'\\') printf("\\%c", (int)*text);
        else if (*text < 32 || *text >= 127) printf("\\u%04x", (unsigned int)*text);
        else putchar((int)*text);
    }
    putchar('"');
}
static void json_module(const struct module_info *info)
{
    printf("{\"path\":"); json_wide(info->path);
    printf(",\"sha256\":"); json_ascii(info->sha256);
    printf(",\"disk_machine\":%u,\"loaded_machine\":%u,\"chpe_version\":%lu,"
           "\"native_ec_ranges\":%lu,\"identity_verified\":%s,\"identity_error\":",
           (unsigned int)info->disk_machine, (unsigned int)info->loaded_machine,
           (unsigned long)info->chpe_version, (unsigned long)info->ec_range_count,
           info->identity_verified ? "true" : "false");
    json_ascii(info->identity_error ? info->identity_error : "");
    putchar('}');
}
static BOOL is_fixture_adapter(const DXGI_ADAPTER_DESC1 *description)
{
    return wcsstr(description->Description, L"llvmpipe") != NULL ||
           wcsstr(description->Description, L"lavapipe") != NULL;
}
static BOOL is_thor_adapter(const DXGI_ADAPTER_DESC1 *description)
{
    return description->VendorId == 0x5143u && !(description->Flags & DXGI_ADAPTER_FLAG_SOFTWARE) &&
        (wcsstr(description->Description, L"Adreno") != NULL) && !is_fixture_adapter(description);
}
static BOOL check_color(const BYTE actual[4], const BYTE expected[4])
{
    unsigned int i;
    for (i = 0; i < 4; ++i) if (abs((int)actual[i] - (int)expected[i]) > 1) return FALSE;
    return TRUE;
}
static void pump_messages(void)
{
    MSG message;
    while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) {
        TranslateMessage(&message); DispatchMessageW(&message);
    }
}

int wmain(int argc, WCHAR **argv)
{
    static const char shader[] =
        "float4 vs_main(float2 p:POSITION):SV_Position{return float4(p,0,1);}\n"
        "float4 ps_main():SV_Target{return float4(0.125,0.875,0.25,1);}\n";
    static const float vertices[] = {-0.8f,-0.8f, 0.0f,0.8f, 0.8f,-0.8f};
    static const float clear[] = {0.03125f,0.0625f,0.09375f,1.0f};
    static const float present_clear[][4] = {
        {0.03125f,0.0625f,0.09375f,1.0f},
        {0.1875f,0.125f,0.0625f,1.0f},
        {0.0625f,0.1875f,0.125f,1.0f}};
    static const BYTE present_corner[][4] = {
        {8,16,24,255}, {48,32,16,255}, {16,48,32,255}};
    static const BYTE expected_center[] = {32,223,64,255}, expected_corner[] = {8,16,24,255};
    static const D3D_FEATURE_LEVEL levels[] = {D3D_FEATURE_LEVEL_11_1,D3D_FEATURE_LEVEL_11_0};
    static const D3D11_INPUT_ELEMENT_DESC input[] = {
        {"POSITION",0,DXGI_FORMAT_R32G32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0}};
    HMODULE d3d11_module = NULL, dxgi_module = NULL, compiler_module = NULL;
    struct module_info d3d11_info = {0}, dxgi_info = {0};
    create_factory_fn create_factory;
    create_device_fn create_device;
    compile_fn compile;
    IDXGIFactory1 *factory = NULL;
    IDXGIAdapter1 *adapter = NULL, *candidate = NULL;
    DXGI_ADAPTER_DESC1 description = {0};
    ID3D11Device *device = NULL;
    ID3D11DeviceContext *context = NULL;
    ID3D11Texture2D *target = NULL, *staging = NULL, *backbuffer = NULL;
    ID3D11RenderTargetView *target_view = NULL, *back_view = NULL;
    ID3D11VertexShader *vertex_shader = NULL;
    ID3D11PixelShader *pixel_shader = NULL;
    ID3D11InputLayout *layout = NULL;
    ID3D11Buffer *vertex_buffer = NULL;
    ID3D11RasterizerState *rasterizer = NULL;
    ID3DBlob *vertex_code = NULL, *pixel_code = NULL, *errors = NULL;
    IDXGISwapChain *swapchain = NULL;
    D3D_FEATURE_LEVEL feature_level = 0;
    D3D11_TEXTURE2D_DESC texture = {0};
    D3D11_BUFFER_DESC buffer = {0};
    D3D11_SUBRESOURCE_DATA initial = {0};
    D3D11_RASTERIZER_DESC raster = {0};
    D3D11_VIEWPORT viewport = {0};
    D3D11_MAPPED_SUBRESOURCE mapped = {0};
    DXGI_SWAP_CHAIN_DESC swap = {0};
    WNDCLASSW window_class = {0};
    HWND window = NULL;
    ATOM registered = 0;
    UINT stride = 2 * sizeof(float), offset = 0, index, present_count = 0;
    BYTE center[4] = {0}, corner[4] = {0};
    BOOL fixture = FALSE, success = FALSE, pixels_verified = FALSE;
    HRESULT hr = E_INVALIDARG;
    const char *stage = "arguments";
    DWORD win32_error = 0;
    ULONGLONG begin = GetTickCount64();

    /* mode, exact loaded d3d11 Windows path, hash, exact loaded dxgi Windows path, hash */
    if (argc != 6 || (wcscmp(argv[1], L"hardware") && wcscmp(argv[1], L"fixture"))) goto cleanup;
    fixture = !wcscmp(argv[1], L"fixture");
    /* The synthetic window contract uses physical X11 pixels, independent of
     * any DPI value in the existing prefix. This setting is process-local. */
    SetProcessDPIAware();
    stage = "load_dxgi";
    dxgi_module = LoadLibraryW(L"dxgi.dll");
    if (!dxgi_module) FAIL_WIN32();
    stage = "verify_dxgi_native_identity";
    if (!qualify_module(dxgi_module, argv[4], argv[5], &dxgi_info)) {
        FAIL_WIN32();
    }
    stage = "load_d3d11";
    d3d11_module = LoadLibraryW(L"d3d11.dll");
    if (!d3d11_module) FAIL_WIN32();
    stage = "verify_d3d11_native_identity";
    if (!qualify_module(d3d11_module, argv[2], argv[3], &d3d11_info)) {
        FAIL_WIN32();
    }
    stage = "resolve_native_entrypoints";
    /* FARPROC assignments via memcpy avoid compiler-specific function-pointer casts. */
    { FARPROC p = GetProcAddress(dxgi_module, "CreateDXGIFactory1"); memcpy(&create_factory, &p, sizeof(p)); }
    { FARPROC p = GetProcAddress(d3d11_module, "D3D11CreateDevice"); memcpy(&create_device, &p, sizeof(p)); }
    if (!create_factory || !create_device) {
        win32_error = ERROR_PROC_NOT_FOUND; hr = HRESULT_FROM_WIN32(win32_error); goto cleanup;
    }
    CHECK_OBJECT(create_factory(&factory1_iid, (void **)&factory), factory, "create_dxgi_factory");
    stage = "select_adapter";
    for (index = 0; index < 16; ++index) {
        DXGI_ADAPTER_DESC1 desc = {0};
        hr = IDXGIFactory1_EnumAdapters1(factory, index, &candidate);
        if (hr == DXGI_ERROR_NOT_FOUND) break;
        if (FAILED(hr)) goto cleanup;
        if (!candidate) { hr = E_UNEXPECTED; goto cleanup; }
        hr = IDXGIAdapter1_GetDesc1(candidate, &desc);
        if (FAILED(hr)) goto cleanup;
        desc.Description[sizeof(desc.Description) / sizeof(desc.Description[0]) - 1] = 0;
        /* Retain the last rejected adapter for a useful failure diagnostic. */
        description = desc;
        if ((fixture && is_fixture_adapter(&desc)) || (!fixture && is_thor_adapter(&desc))) {
            adapter = candidate; candidate = NULL; break;
        }
        RELEASE(IDXGIAdapter1, candidate);
    }
    if (!adapter) { hr = DXGI_ERROR_NOT_FOUND; goto cleanup; }
    stage = "create_d3d11_device";
    hr = create_device((IDXGIAdapter *)adapter, D3D_DRIVER_TYPE_UNKNOWN, NULL, 0,
        levels, sizeof(levels) / sizeof(levels[0]), D3D11_SDK_VERSION, &device,
        &feature_level, &context);
    /* Windows runtimes without D3D11.1 reject the request array rather than
     * trying its D3D11.0 member. Retry the same adapter, never WARP/software. */
    if (hr == E_INVALIDARG) {
        RELEASE(ID3D11DeviceContext, context); RELEASE(ID3D11Device, device);
        hr = create_device((IDXGIAdapter *)adapter, D3D_DRIVER_TYPE_UNKNOWN, NULL, 0,
            levels + 1, 1, D3D11_SDK_VERSION, &device, &feature_level, &context);
    }
    if (FAILED(hr)) goto cleanup;
    if (!device || !context) { hr = E_UNEXPECTED; goto cleanup; }
    if (feature_level < D3D_FEATURE_LEVEL_11_0) { stage = "feature_level"; hr = E_FAIL; goto cleanup; }
    stage = "load_shader_compiler";
    compiler_module = LoadLibraryW(L"d3dcompiler_47.dll");
    if (!compiler_module) FAIL_WIN32();
    { FARPROC p = GetProcAddress(compiler_module, "D3DCompile"); memcpy(&compile, &p, sizeof(p)); }
    if (!compile) {
        win32_error = ERROR_PROC_NOT_FOUND; hr = HRESULT_FROM_WIN32(win32_error); goto cleanup;
    }
    CHECK_OBJECT(compile(shader, sizeof(shader)-1, "original-eve-probe.hlsl", NULL, NULL,
        "vs_main", "vs_5_0", D3DCOMPILE_ENABLE_STRICTNESS, 0, &vertex_code, &errors), vertex_code, "compile_vertex_shader");
    RELEASE(ID3D10Blob, errors);
    CHECK_OBJECT(compile(shader, sizeof(shader)-1, "original-eve-probe.hlsl", NULL, NULL,
        "ps_main", "ps_5_0", D3DCOMPILE_ENABLE_STRICTNESS, 0, &pixel_code, &errors), pixel_code, "compile_pixel_shader");
    RELEASE(ID3D10Blob, errors);
    CHECK_OBJECT(ID3D11Device_CreateVertexShader(device, ID3D10Blob_GetBufferPointer(vertex_code),
        ID3D10Blob_GetBufferSize(vertex_code), NULL, &vertex_shader), vertex_shader, "create_vertex_shader");
    CHECK_OBJECT(ID3D11Device_CreatePixelShader(device, ID3D10Blob_GetBufferPointer(pixel_code),
        ID3D10Blob_GetBufferSize(pixel_code), NULL, &pixel_shader), pixel_shader, "create_pixel_shader");
    CHECK_OBJECT(ID3D11Device_CreateInputLayout(device, input, 1, ID3D10Blob_GetBufferPointer(vertex_code),
        ID3D10Blob_GetBufferSize(vertex_code), &layout), layout, "create_input_layout");
    buffer.ByteWidth = sizeof(vertices); buffer.Usage = D3D11_USAGE_IMMUTABLE;
    buffer.BindFlags = D3D11_BIND_VERTEX_BUFFER; initial.pSysMem = vertices;
    CHECK_OBJECT(ID3D11Device_CreateBuffer(device, &buffer, &initial, &vertex_buffer), vertex_buffer, "create_vertex_buffer");
    raster.FillMode = D3D11_FILL_SOLID; raster.CullMode = D3D11_CULL_NONE; raster.DepthClipEnable = TRUE;
    CHECK_OBJECT(ID3D11Device_CreateRasterizerState(device, &raster, &rasterizer), rasterizer, "create_rasterizer");
    texture.Width = texture.Height = IMAGE_SIDE; texture.MipLevels = texture.ArraySize = 1;
    texture.Format = DXGI_FORMAT_R8G8B8A8_UNORM; texture.SampleDesc.Count = 1;
    texture.Usage = D3D11_USAGE_DEFAULT; texture.BindFlags = D3D11_BIND_RENDER_TARGET;
    CHECK_OBJECT(ID3D11Device_CreateTexture2D(device, &texture, NULL, &target), target, "create_offscreen_target");
    CHECK_OBJECT(ID3D11Device_CreateRenderTargetView(device, (ID3D11Resource *)target, NULL, &target_view), target_view, "create_offscreen_rtv");
    texture.Usage = D3D11_USAGE_STAGING; texture.BindFlags = 0; texture.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    CHECK_OBJECT(ID3D11Device_CreateTexture2D(device, &texture, NULL, &staging), staging, "create_staging_target");
    viewport.Width = viewport.Height = (float)IMAGE_SIDE; viewport.MaxDepth = 1;
    ID3D11DeviceContext_OMSetRenderTargets(context, 1, &target_view, NULL);
    ID3D11DeviceContext_RSSetState(context, rasterizer);
    ID3D11DeviceContext_RSSetViewports(context, 1, &viewport);
    ID3D11DeviceContext_IASetInputLayout(context, layout);
    ID3D11DeviceContext_IASetVertexBuffers(context, 0, 1, &vertex_buffer, &stride, &offset);
    ID3D11DeviceContext_IASetPrimitiveTopology(context, D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    ID3D11DeviceContext_VSSetShader(context, vertex_shader, NULL, 0);
    ID3D11DeviceContext_PSSetShader(context, pixel_shader, NULL, 0);
    ID3D11DeviceContext_ClearRenderTargetView(context, target_view, clear);
    ID3D11DeviceContext_Draw(context, 3, 0);
    ID3D11DeviceContext_OMSetRenderTargets(context, 0, NULL, NULL);
    ID3D11DeviceContext_CopyResource(context, (ID3D11Resource *)staging, (ID3D11Resource *)target);
    CHECK(ID3D11DeviceContext_Map(context, (ID3D11Resource *)staging, 0, D3D11_MAP_READ, 0, &mapped), "map_readback");
    if (!mapped.pData || mapped.RowPitch < IMAGE_SIDE * 4u || mapped.RowPitch > 16u * 1024u * 1024u) {
        ID3D11DeviceContext_Unmap(context, (ID3D11Resource *)staging, 0);
        stage = "readback_layout"; hr = E_FAIL; goto cleanup;
    }
    memcpy(center, (const BYTE *)mapped.pData + (size_t)mapped.RowPitch * (IMAGE_SIDE/2) + 4 * (IMAGE_SIDE/2), 4);
    memcpy(corner, (const BYTE *)mapped.pData + (size_t)mapped.RowPitch * 2 + 8, 4);
    ID3D11DeviceContext_Unmap(context, (ID3D11Resource *)staging, 0);
    stage = "verify_shader_pixels";
    if (!check_color(center, expected_center) || !check_color(corner, expected_corner)) { hr = E_FAIL; goto cleanup; }
    pixels_verified = TRUE;
    stage = "create_window";
    window_class.lpfnWndProc = DefWindowProcW;
    window_class.hInstance = GetModuleHandleW(NULL);
    window_class.lpszClassName = L"EveNativeD3DQualification";
    registered = RegisterClassW(&window_class);
    if (!registered || !(window = CreateWindowW(window_class.lpszClassName, L"EVE GPU qualification",
        WS_POPUP, 32, 32, IMAGE_SIDE, IMAGE_SIDE, NULL, NULL, window_class.hInstance, NULL))) {
        FAIL_WIN32();
    }
    ShowWindow(window, SW_SHOW); UpdateWindow(window); pump_messages();
    swap.BufferDesc.Width = swap.BufferDesc.Height = IMAGE_SIDE;
    swap.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    swap.SampleDesc.Count = 1; swap.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    swap.BufferCount = 2; swap.OutputWindow = window; swap.Windowed = TRUE;
    swap.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
    CHECK_OBJECT(IDXGIFactory1_CreateSwapChain(factory, (IUnknown *)device, &swap, &swapchain), swapchain, "create_window_swapchain");
    CHECK_OBJECT(IDXGISwapChain_GetBuffer(swapchain, 0, &texture2d_iid, (void **)&backbuffer), backbuffer, "get_window_backbuffer");
    CHECK_OBJECT(ID3D11Device_CreateRenderTargetView(device, (ID3D11Resource *)backbuffer, NULL, &back_view), back_view, "create_window_rtv");
    for (index = 0; index < 3; ++index) {
        ID3D11DeviceContext_OMSetRenderTargets(context, 1, &back_view, NULL);
        ID3D11DeviceContext_ClearRenderTargetView(context, back_view, present_clear[index]);
        ID3D11DeviceContext_Draw(context, 3, 0);
        /* Exercise the game's vsync request. The private DXVK policy must
         * still present these frames in immediate mode to the local display. */
        CHECK(IDXGISwapChain_Present(swapchain, REQUESTED_SYNC_INTERVAL, 0), "present_window_frame");
        if (hr != S_OK) { stage = "present_not_visible"; hr = E_FAIL; goto cleanup; }
        ++present_count; pump_messages();
        /* A bounded hold gives independent X11/RFB qualification enough time
         * to observe each real present. API S_OK alone is not display proof. */
        fprintf(stderr, "{\"helper\":\"eve-d3d11-frame-1\",\"frame\":%u,"
            "\"requested_sync_interval\":%u,"
            "\"window\":{\"x\":32,\"y\":32,\"width\":128,\"height\":128},"
            "\"center_rgba\":[32,223,64,255],\"corner_rgba\":[%u,%u,%u,%u],\"hold_ms\":%u}\n",
            index, REQUESTED_SYNC_INTERVAL, present_corner[index][0], present_corner[index][1],
            present_corner[index][2], present_corner[index][3], index == 2 ? 1000u : 500u);
        fflush(stderr);
        Sleep(index == 2 ? 1000u : 500u);
    }
    CHECK(ID3D11Device_GetDeviceRemovedReason(device), "device_status_after_present");
    success = TRUE; stage = "passed"; hr = S_OK;
cleanup:
    /* GetLastError is not meaningful after COM HRESULTs or logical checks.
     * Preserve only errors captured immediately after failed Win32 calls. */
    if (context) { ID3D11DeviceContext_ClearState(context); ID3D11DeviceContext_Flush(context); }
    RELEASE(ID3D11RenderTargetView, back_view); RELEASE(ID3D11Texture2D, backbuffer);
    RELEASE(IDXGISwapChain, swapchain);
    if (window) DestroyWindow(window);
    if (registered) UnregisterClassW(window_class.lpszClassName, window_class.hInstance);
    RELEASE(ID3D11RenderTargetView, target_view); RELEASE(ID3D11Texture2D, target);
    RELEASE(ID3D11Texture2D, staging); RELEASE(ID3D11RasterizerState, rasterizer);
    RELEASE(ID3D11Buffer, vertex_buffer); RELEASE(ID3D11InputLayout, layout);
    RELEASE(ID3D11VertexShader, vertex_shader); RELEASE(ID3D11PixelShader, pixel_shader);
    RELEASE(ID3D10Blob, vertex_code); RELEASE(ID3D10Blob, pixel_code); RELEASE(ID3D10Blob, errors);
    RELEASE(ID3D11DeviceContext, context); RELEASE(ID3D11Device, device);
    RELEASE(IDXGIAdapter1, candidate); RELEASE(IDXGIAdapter1, adapter); RELEASE(IDXGIFactory1, factory);
    if (compiler_module) FreeLibrary(compiler_module);
    if (d3d11_module) FreeLibrary(d3d11_module);
    if (dxgi_module) FreeLibrary(dxgi_module);
    printf("{\"helper\":\"eve-d3d11-probe-1\",\"mode\":\"%s\",\"passed\":%s,\"stage\":",
        fixture ? "fixture" : "hardware", success ? "true" : "false"); json_ascii(stage);
    printf(",\"hresult\":%lu,\"win32_error\":%lu,\"d3d11\":", (unsigned long)(DWORD)hr, (unsigned long)win32_error);
    json_module(&d3d11_info); printf(",\"dxgi\":"); json_module(&dxgi_info);
    printf(",\"adapter\":{\"description\":"); json_wide(description.Description);
    printf(",\"vendor_id\":%u,\"device_id\":%u,\"flags\":%u,"
        "\"dedicated_video_memory\":%llu,\"dedicated_system_memory\":%llu,\"shared_system_memory\":%llu},"
        "\"feature_level\":%u,"
        "\"pixels_verified\":%s,\"offscreen_pixels_verified\":%s,\"display_pixels_verified\":false,"
        "\"center_rgba\":[%u,%u,%u,%u],\"corner_rgba\":[%u,%u,%u,%u],"
        "\"present_count\":%u,\"requested_sync_interval\":%u,\"elapsed_ms\":%llu}\n", description.VendorId, description.DeviceId,
        description.Flags, (unsigned long long)description.DedicatedVideoMemory,
        (unsigned long long)description.DedicatedSystemMemory, (unsigned long long)description.SharedSystemMemory,
        (unsigned int)feature_level, pixels_verified ? "true" : "false",
        pixels_verified ? "true" : "false",
        center[0],center[1],center[2],center[3],corner[0],corner[1],corner[2],corner[3],present_count,REQUESTED_SYNC_INTERVAL,
        (unsigned long long)(GetTickCount64()-begin));
    return success ? 0 : 1;
}

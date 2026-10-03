/*
 * Original private-prefix CryptoAPI and direct localhost TLS qualification.
 * This helper runs as x64 through the existing Wine/FEX runtime. It never
 * changes Android trust, disables TLS verification, or accepts a remote URL.
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
#include <wincrypt.h>
#include <winhttp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CA_LIMIT (128u * 1024u)
#define BODY_LIMIT (32u * 1024u)

static void json_string(const char *value)
{
    const unsigned char *cursor = (const unsigned char *)value;
    putchar('"');
    while (*cursor) {
        unsigned char byte = *cursor++;
        if (byte == '"' || byte == '\\') printf("\\%c", byte);
        else if (byte < 0x20 || byte >= 0x7f) printf("\\u%04x", (unsigned int)byte);
        else putchar(byte);
    }
    putchar('"');
}

static BOOL certificate_hash(PCCERT_CONTEXT certificate, char output[65])
{
    BYTE hash[32];
    DWORD length = sizeof(hash);
    unsigned int index;
    if (!CryptHashCertificate2(L"SHA256", 0, NULL, certificate->pbCertEncoded,
                              certificate->cbCertEncoded, hash, &length)) return FALSE;
    if (length != sizeof(hash)) {
        SetLastError(ERROR_INVALID_DATA);
        return FALSE;
    }
    for (index = 0; index < sizeof(hash); index++) sprintf(output + index * 2, "%02x", hash[index]);
    output[64] = 0;
    return TRUE;
}

static BOOL same_certificate(PCCERT_CONTEXT left, PCCERT_CONTEXT right)
{
    return left->cbCertEncoded == right->cbCertEncoded &&
           !memcmp(left->pbCertEncoded, right->pbCertEncoded, left->cbCertEncoded);
}

static BOOL verify_chain(PCCERT_CONTEXT certificate, PCCERT_CONTEXT expected_root,
                         BOOL ssl, DWORD *error)
{
    CERT_CHAIN_PARA parameters = {0};
    CERT_CHAIN_POLICY_PARA policy = {0};
    CERT_CHAIN_POLICY_STATUS status = {0};
    SSL_EXTRA_CERT_CHAIN_POLICY_PARA ssl_parameters = {0};
    PCCERT_CHAIN_CONTEXT chain = NULL;
    PCERT_SIMPLE_CHAIN simple;
    BOOL success = FALSE;

    parameters.cbSize = sizeof(parameters);
    if (!CertGetCertificateChain(NULL, certificate, NULL, NULL, &parameters,
                                 CERT_CHAIN_CACHE_ONLY_URL_RETRIEVAL |
                                 CERT_CHAIN_DISABLE_AUTH_ROOT_AUTO_UPDATE,
                                 NULL, &chain)) {
        *error = GetLastError();
        return FALSE;
    }
    policy.cbSize = sizeof(policy);
    status.cbSize = sizeof(status);
    if (ssl) {
        ssl_parameters.cbSize = sizeof(ssl_parameters);
        ssl_parameters.dwAuthType = AUTHTYPE_SERVER;
        ssl_parameters.pwszServerName = L"localhost";
        policy.pvExtraPolicyPara = &ssl_parameters;
    }
    if (!CertVerifyCertificateChainPolicy(ssl ? CERT_CHAIN_POLICY_SSL : CERT_CHAIN_POLICY_BASE,
                                          chain, &policy, &status)) {
        *error = GetLastError();
        goto cleanup;
    }
    if (status.dwError) {
        *error = status.dwError;
        goto cleanup;
    }
    if (!chain->cChain || !(simple = chain->rgpChain[0]) || !simple->cElement ||
        !same_certificate(simple->rgpElement[simple->cElement - 1]->pCertContext, expected_root)) {
        *error = ERROR_INVALID_DATA;
        goto cleanup;
    }
    success = TRUE;
cleanup:
    CertFreeCertificateChain(chain);
    return success;
}

int wmain(int argc, WCHAR **argv)
{
    HANDLE file = INVALID_HANDLE_VALUE;
    LARGE_INTEGER size;
    char *pem = NULL;
    BYTE *der = NULL;
    DWORD bytes = 0, der_length = 0, error = 0;
    DWORD http_status = 0, status_length = sizeof(http_status);
    DWORD disable = WINHTTP_DISABLE_REDIRECTS;
    DWORD body_length = 0, read_length;
    char body[BODY_LIMIT + 1] = {0};
    char ca_hash[65] = {0};
    const char *stage = "arguments";
    BOOL success = FALSE, trust_passed = FALSE, tls_passed = FALSE;
    HCERTSTORE store = NULL;
    PCCERT_CONTEXT ca = NULL, stored = NULL, peer = NULL;
    HINTERNET session = NULL, connection = NULL, request = NULL;

    if (argc != 2) {
        error = ERROR_INVALID_PARAMETER;
        goto cleanup;
    }
    stage = "read_private_ca";
    file = CreateFileW(argv[1], GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                       FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE || !GetFileSizeEx(file, &size)) {
        error = GetLastError();
        goto cleanup;
    }
    if (size.QuadPart <= 0 || size.QuadPart > CA_LIMIT) {
        error = ERROR_FILE_TOO_LARGE;
        goto cleanup;
    }
    pem = (char *)calloc((size_t)size.QuadPart + 1, 1);
    if (!pem) {
        error = ERROR_NOT_ENOUGH_MEMORY;
        goto cleanup;
    }
    if (!ReadFile(file, pem, (DWORD)size.QuadPart, &bytes, NULL) || bytes != (DWORD)size.QuadPart) {
        error = GetLastError();
        if (!error) error = ERROR_HANDLE_EOF;
        goto cleanup;
    }
    CloseHandle(file);
    file = INVALID_HANDLE_VALUE;
    stage = "decode_private_ca";
    if (!CryptStringToBinaryA(pem, bytes, CRYPT_STRING_BASE64HEADER, NULL, &der_length, NULL, NULL)) {
        error = GetLastError();
        goto cleanup;
    }
    der = (BYTE *)malloc(der_length);
    if (!der) {
        error = ERROR_NOT_ENOUGH_MEMORY;
        goto cleanup;
    }
    if (!CryptStringToBinaryA(pem, bytes, CRYPT_STRING_BASE64HEADER, der, &der_length, NULL, NULL) ||
        !(ca = CertCreateCertificateContext(X509_ASN_ENCODING, der, der_length)) ||
        !certificate_hash(ca, ca_hash)) {
        error = GetLastError();
        goto cleanup;
    }

    stage = "import_current_user_root";
    store = CertOpenStore(CERT_STORE_PROV_SYSTEM_W, 0, 0, CERT_SYSTEM_STORE_CURRENT_USER, L"ROOT");
    if (!store || !CertAddEncodedCertificateToStore(store, X509_ASN_ENCODING,
                                                   ca->pbCertEncoded, ca->cbCertEncoded,
                                                   CERT_STORE_ADD_REPLACE_EXISTING, NULL)) {
        error = GetLastError();
        goto cleanup;
    }
    /* Wine flushes its registry-backed certificate store on close. Reopen it
     * before checking the default chain engine or claiming persisted trust. */
    if (!CertCloseStore(store, 0)) {
        error = GetLastError();
        store = NULL;
        goto cleanup;
    }
    store = NULL;
    /* Read back the exact certificate; a successful stub cannot qualify trust. */
    stage = "verify_current_user_root";
    store = CertOpenStore(CERT_STORE_PROV_SYSTEM_W, 0, 0,
                          CERT_SYSTEM_STORE_CURRENT_USER | CERT_STORE_READONLY_FLAG, L"ROOT");
    if (!store) {
        error = GetLastError();
        goto cleanup;
    }
    stored = CertFindCertificateInStore(store, X509_ASN_ENCODING, 0, CERT_FIND_EXISTING, ca, NULL);
    if (!stored || !same_certificate(stored, ca)) {
        error = GetLastError();
        if (!error) error = ERROR_INVALID_DATA;
        goto cleanup;
    }
    if (!verify_chain(stored, ca, FALSE, &error)) goto cleanup;
    trust_passed = TRUE;

    stage = "connect_direct_localhost443";
    session = WinHttpOpen(L"EVE-Android-Private-Gate/1", WINHTTP_ACCESS_TYPE_NO_PROXY,
                          WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session || !WinHttpSetTimeouts(session, 8000, 8000, 8000, 8000) ||
        !(connection = WinHttpConnect(session, L"localhost", INTERNET_DEFAULT_HTTPS_PORT, 0)) ||
        !(request = WinHttpOpenRequest(connection, L"GET", L"/health", NULL,
                                       WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES,
                                       WINHTTP_FLAG_SECURE)) ||
        !WinHttpSetOption(request, WINHTTP_OPTION_DISABLE_FEATURE, &disable, sizeof(disable)) ||
        !WinHttpSendRequest(request, WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                            WINHTTP_NO_REQUEST_DATA, 0, 0, 0) ||
        !WinHttpReceiveResponse(request, NULL)) {
        error = GetLastError();
        goto cleanup;
    }
    stage = "verify_localhost_peer_chain";
    status_length = sizeof(peer);
    if (!WinHttpQueryOption(request, WINHTTP_OPTION_SERVER_CERT_CONTEXT, &peer, &status_length)) {
        error = GetLastError();
        goto cleanup;
    }
    if (!verify_chain(peer, ca, TRUE, &error)) goto cleanup;
    tls_passed = TRUE;

    stage = "read_local_health";
    status_length = sizeof(http_status);
    if (!WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                             WINHTTP_HEADER_NAME_BY_INDEX, &http_status, &status_length,
                             WINHTTP_NO_HEADER_INDEX)) {
        error = GetLastError();
        goto cleanup;
    }
    if (http_status != 200) {
        error = ERROR_INVALID_DATA;
        goto cleanup;
    }
    do {
        if (body_length == BODY_LIMIT) {
            error = ERROR_INSUFFICIENT_BUFFER;
            goto cleanup;
        }
        if (!WinHttpReadData(request, body + body_length, BODY_LIMIT - body_length, &read_length)) {
            error = GetLastError();
            goto cleanup;
        }
        body_length += read_length;
    } while (read_length);
    body[body_length] = 0;
    if (!body_length) {
        error = ERROR_INVALID_DATA;
        goto cleanup;
    }
    stage = "qualified";
    success = TRUE;

cleanup:
    if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
    if (peer) CertFreeCertificateContext(peer);
    if (stored) CertFreeCertificateContext(stored);
    if (ca) CertFreeCertificateContext(ca);
    if (store) CertCloseStore(store, 0);
    if (request) WinHttpCloseHandle(request);
    if (connection) WinHttpCloseHandle(connection);
    if (session) WinHttpCloseHandle(session);
    free(der);
    free(pem);
    printf("{\"format\":1,\"helper\":\"eve-client-gate-1\",\"success\":%s,"
           "\"phase\":\"%s\",\"wine_cryptoapi_trust\":%s,\"localhost443_tls\":%s,"
           "\"root_store\":\"CurrentUser\\\\ROOT\",\"ca_der_sha256\":\"%s\","
           "\"tls_url\":\"https://localhost/health\",\"tls_proxy\":\"none\","
           "\"tls_certificate_checks\":\"default\",\"http_status\":%lu,\"response_body\":",
           success ? "true" : "false", success ? "client_tls_qualified" : "client_tls_failed",
           trust_passed ? "true" : "false", tls_passed ? "true" : "false", ca_hash,
           (unsigned long)http_status);
    json_string(body);
    printf(",\"stage\":");
    json_string(stage);
    printf(",\"win32_error\":%lu}\n", (unsigned long)error);
    return success ? 0 : 1;
}

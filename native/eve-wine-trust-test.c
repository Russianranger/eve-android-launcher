/* Focused CryptoAPI regression probe for the unchanged EveJS private CA.
 * Run as native ARM64 PE in a disposable Wine prefix; FEX is not required.
 * This test never changes validation policy or ignores a trust error. */
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
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CERTIFICATE_LIMIT (128u * 1024u)

static void diagnostic_stage(const char *stage)
{
    fprintf(stderr, "Wine trust probe: %s\n", stage);
    fflush(stderr);
}

static PCCERT_CONTEXT read_certificate(const WCHAR *path)
{
    HANDLE file;
    LARGE_INTEGER size;
    DWORD read = 0;
    BYTE *data;
    PCCERT_CONTEXT result = NULL;

    file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL,
                       OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return NULL;
    if (!GetFileSizeEx(file, &size) || size.QuadPart <= 0 ||
        size.QuadPart > CERTIFICATE_LIMIT) {
        CloseHandle(file);
        SetLastError(ERROR_INVALID_DATA);
        return NULL;
    }
    data = malloc((size_t)size.QuadPart);
    if (data && ReadFile(file, data, (DWORD)size.QuadPart, &read, NULL) &&
        read == (DWORD)size.QuadPart)
        result = CertCreateCertificateContext(X509_ASN_ENCODING, data, read);
    free(data);
    CloseHandle(file);
    return result;
}

static BOOL same_certificate(PCCERT_CONTEXT left, PCCERT_CONTEXT right)
{
    return left->cbCertEncoded == right->cbCertEncoded &&
           !memcmp(left->pbCertEncoded, right->pbCertEncoded, left->cbCertEncoded);
}

int wmain(int argc, WCHAR **argv)
{
    PCCERT_CONTEXT root = NULL, leaf = NULL, stored = NULL;
    PCCERT_CHAIN_CONTEXT chain = NULL;
    HCERTSTORE store = NULL;
    CERT_CHAIN_PARA parameters = {0};
    CERT_CHAIN_POLICY_PARA policy = {0};
    CERT_CHAIN_POLICY_STATUS status = {0};
    SSL_EXTRA_CERT_CHAIN_POLICY_PARA ssl = {0};
    char *usage = szOID_PKIX_KP_SERVER_AUTH;
    DWORD error = 0;
    BOOL root_matches = FALSE, passed = FALSE;
    const char *stage = "arguments";
    int exit_code = 2;

    setvbuf(stdout, NULL, _IONBF, 0);
    diagnostic_stage(stage);

    if (argc != 4) {
        error = ERROR_INVALID_PARAMETER;
        goto cleanup;
    }
    stage = "read_test_certificates";
    diagnostic_stage(stage);
    root = read_certificate(argv[1]);
    leaf = read_certificate(argv[2]);
    if (!root || !leaf) {
        error = GetLastError();
        goto cleanup;
    }
    stage = "import_test_current_user_root";
    diagnostic_stage(stage);
    store = CertOpenStore(CERT_STORE_PROV_SYSTEM_W, 0, 0,
                          CERT_SYSTEM_STORE_CURRENT_USER, L"ROOT");
    if (!store || !CertAddCertificateContextToStore(store, root,
                                                   CERT_STORE_ADD_REPLACE_EXISTING, NULL)) {
        error = GetLastError();
        goto cleanup;
    }
    if (!CertCloseStore(store, 0)) {
        error = GetLastError();
        store = NULL;
        goto cleanup;
    }
    store = NULL;
    stage = "read_back_test_root";
    diagnostic_stage(stage);
    store = CertOpenStore(CERT_STORE_PROV_SYSTEM_W, 0, 0,
                          CERT_SYSTEM_STORE_CURRENT_USER | CERT_STORE_READONLY_FLAG,
                          L"ROOT");
    if (!store || !(stored = CertFindCertificateInStore(store, X509_ASN_ENCODING,
                        0, CERT_FIND_EXISTING, root, NULL)) || !same_certificate(stored, root)) {
        error = GetLastError();
        if (!error) error = ERROR_INVALID_DATA;
        goto cleanup;
    }

    stage = "build_leaf_chain";
    diagnostic_stage(stage);
    parameters.cbSize = sizeof(parameters);
    parameters.RequestedUsage.Usage.cUsageIdentifier = 1;
    parameters.RequestedUsage.Usage.rgpszUsageIdentifier = &usage;
    if (!CertGetCertificateChain(NULL, leaf, NULL, NULL, &parameters,
                                 CERT_CHAIN_CACHE_ONLY_URL_RETRIEVAL |
                                 CERT_CHAIN_DISABLE_AUTH_ROOT_AUTO_UPDATE, NULL, &chain)) {
        error = GetLastError();
        goto cleanup;
    }
    stage = "verify_ssl_policy";
    diagnostic_stage(stage);
    policy.cbSize = sizeof(policy);
    status.cbSize = sizeof(status);
    ssl.cbSize = sizeof(ssl);
    ssl.dwAuthType = AUTHTYPE_SERVER;
    ssl.pwszServerName = argv[3];
    policy.pvExtraPolicyPara = &ssl;
    if (!CertVerifyCertificateChainPolicy(CERT_CHAIN_POLICY_SSL, chain, &policy, &status)) {
        error = GetLastError();
        goto cleanup;
    }
    if (chain->cChain && chain->rgpChain[0]->cElement) {
        PCERT_SIMPLE_CHAIN simple = chain->rgpChain[0];
        root_matches = same_certificate(
            simple->rgpElement[simple->cElement - 1]->pCertContext, root);
    }
    passed = !chain->TrustStatus.dwErrorStatus && !status.dwError && root_matches;
    printf("{\"completed\":true,\"pass\":%s,\"chain_error_status\":%lu,"
           "\"ssl_policy_error\":%lu,\"exact_root\":%s,\"chain_elements\":%lu}\n",
           passed ? "true" : "false", chain->TrustStatus.dwErrorStatus,
           status.dwError, root_matches ? "true" : "false",
           chain->cChain ? chain->rgpChain[0]->cElement : 0);
    exit_code = 0;

cleanup:
    diagnostic_stage("cleanup");
    if (exit_code)
        printf("{\"completed\":false,\"stage\":\"%s\",\"win32_error\":%lu}\n", stage, error);
    if (chain) CertFreeCertificateChain(chain);
    if (stored) CertFreeCertificateContext(stored);
    if (store) CertCloseStore(store, 0);
    if (leaf) CertFreeCertificateContext(leaf);
    if (root) CertFreeCertificateContext(root);
    diagnostic_stage("complete");
    return exit_code;
}

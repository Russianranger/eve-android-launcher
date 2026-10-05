/* SPDX-License-Identifier: MIT
 * Read exact physical GPU identity from the already pinned baseline ICD.
 * This creates no device/queue and submits no GPU work. It cannot qualify
 * rendering or the backported register. --fixture is CI metadata evidence
 * only and is never accepted by the retail backend hardware selection gate.
 */
#include <vulkan/vulkan.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static void json_string(const char *value) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)value; *p; ++p) {
        if (*p == '"' || *p == '\\') printf("\\%c", *p);
        else if (*p < 32) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}

int main(int argc, char **argv) {
    int fixture = argc == 2 && !strcmp(argv[1], "--fixture");
    if (argc != 1 && !fixture) return 2;
    if (!fixture) {
        int kgsl = open("/dev/kgsl-3d0", O_RDWR | O_CLOEXEC);
        if (kgsl < 0) {
            fprintf(stderr, "A740 identity requires KGSL access: %s\n", strerror(errno));
            return 1;
        }
        close(kgsl);
    }
    VkApplicationInfo application = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = "EVE baseline GPU identity", .apiVersion = VK_API_VERSION_1_3};
    VkInstanceCreateInfo create = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        .pApplicationInfo = &application};
    VkInstance instance = VK_NULL_HANDLE;
    VkResult result = vkCreateInstance(&create, NULL, &instance);
    if (result != VK_SUCCESS) {
        fprintf(stderr, "Baseline Vulkan identity instance failed: %d\n", result);
        return 1;
    }
    uint32_t count = 0;
    result = vkEnumeratePhysicalDevices(instance, &count, NULL);
    if (result != VK_SUCCESS || count != 1) {
        fprintf(stderr, "Baseline identity requires exactly one pinned physical adapter\n");
        vkDestroyInstance(instance, NULL);
        return 1;
    }
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    result = vkEnumeratePhysicalDevices(instance, &count, &physical);
    if (result != VK_SUCCESS || count != 1) {
        vkDestroyInstance(instance, NULL);
        return 1;
    }
    VkPhysicalDeviceDriverProperties driver = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
    VkPhysicalDeviceProperties2 properties = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2,
        .pNext = &driver};
    vkGetPhysicalDeviceProperties2(physical, &properties);
    int software = properties.properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU;
    int allowed = fixture ? software :
        (!software && properties.properties.vendorID == 0x5143 &&
         /* Mesa exports the FD740 KGSL chip ID, not the model number 0x740. */
         properties.properties.deviceID == 0x43050a01 &&
         driver.driverID == VK_DRIVER_ID_MESA_TURNIP &&
         properties.properties.driverVersion == (26u << 22) &&
         properties.properties.apiVersion >= VK_API_VERSION_1_3);
    printf("{\"helper\":\"eve-a740-driver-probe-1\",\"mode\":\"%s\",\"passed\":%s,\"device\":",
        fixture ? "fixture" : "hardware", allowed ? "true" : "false");
    json_string(properties.properties.deviceName);
    printf(",\"driver\":"); json_string(driver.driverName);
    printf(",\"driver_info\":"); json_string(driver.driverInfo);
    printf(",\"device_id\":%u,\"vendor_id\":%u,\"driver_id\":%u,\"driver_version\":%u,\"api_version\":%u,\"software\":%s}\n",
        properties.properties.deviceID, properties.properties.vendorID, driver.driverID,
        properties.properties.driverVersion, properties.properties.apiVersion,
        software ? "true" : "false");
    vkDestroyInstance(instance, NULL);
    return allowed ? 0 : 1;
}

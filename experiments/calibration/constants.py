eastern_tz = ZoneInfo("America/New_York")


microservices = ['globeco-allocation-service', 'globeco-confirmation-service', 'globeco-execution-service',
                 'globeco-fix-engine', 'globeco-order-generation-service', 'globeco-order-service',
                 'globeco-portfolio-accounting-service', 'globeco-portfolio-management-portal',
                 'globeco-portfolio-service', 'globeco-pricing-service', 'globeco-security-service',
                 'globeco-trade-service']

namespace="globeco"

NODES = (('server', 4, 'rpi'),
         ('node-0', 4, 'rpi'),
         ('node-1', 4, 'rpi'),
         ('node-2', 4, 'rpi'),
         ('node-3', 16, 'amd'),
         ('node-4', 16, 'amd'),
         ('node-5', 16, 'amd'),
        )

METRICS = {
    "k10temp-pci-00c3": "AMD CPU Temperature",
    "amdgpu-pci-0400": "AMD GPU Temperature",
    "acpitz-acpi-0": "Ambiant Temperature",
    "nvme-pci-0100": "NVMe Temperature",
    "cpu_thermal-virtual-0": "RPI CPU Temperature",
    "rp1_adc-isa-0000": "RPI ADC Temperature",
    "nvme-pci-10100": "NVMe Temperature"
}

# Metrics to collect from each node.  Underscores are used in place of dashes for Prometheus queries.
NODE_METRICS = {
    "server": ["cpu_thermal_virtual_0", "rp1_adc_isa_0000", "nvme_pci_10100"],
    "node-0": ["cpu_thermal_virtual_0", "rp1_adc_isa_0000", "nvme_pci_10100"],
    "node-1": ["cpu_thermal_virtual_0", "rp1_adc_isa_0000", "nvme_pci_10100"],
    "node-2": ["cpu_thermal_virtual_0", "rp1_adc_isa_0000", "nvme_pci_10100"],
    "node-3": ["k10temp_pci_00c3", "amdgpu_pci_0400", "acpitz_acpi_0", "nvme_pci_0100"],
    "node-4": ["k10temp_pci_00c3", "amdgpu_pci_0400", "acpitz_acpi_0", "nvme_pci_0100"],
    "node-5": ["k10temp_pci_00c3", "amdgpu_pci_0400", "acpitz_acpi_0", "nvme_pci_0100"],
}

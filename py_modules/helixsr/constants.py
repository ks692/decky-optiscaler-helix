"""Pinned HelixSR release and install constants (OptiScaler route)."""

VERSION = "1.5.1"
RELEASE_URL = (
    "https://github.com/lonewolf0622/HelixSR/releases/download/v1.5.1/HelixSR-1.5.1.zip"
)
RELEASE_SHA256 = "45401aae70bdc7a734ab9f143772abf9c966a20df3fe0b9dfaee487d72408708"
ARCHIVE_ROOT = "HelixSR-1.5.1"
GITHUB_REPO = "lonewolf0622/HelixSR"

# SHA-256 for releases verified out-of-band. "Latest" downloads are checksum
# verified only when their version is listed here; unknown versions proceed
# unverified, with the warning logged, because the user asked for latest.
KNOWN_SHAS = {
    "1.5.1": RELEASE_SHA256,
}

NVNGX_DLL = "nvngx.dll"
SETUP_SCRIPT = "helixsr-setup.sh"
OPTISCALER_INI = "OptiScaler.ini"
HELIX_DIRNAME = "HelixSR"
JOURNAL_NAME = "helixsr-install.json"
READY_MARKER = "helixsr-ready.json"
LAUNCH_RECORD_NAME = "helixsr_previous_launch_options.txt"

# ini keys managed per game, as upstream's helixsr-install.sh does.
INI_DX12_SECTION = "Upscalers"
INI_DX12_KEY = "Dx12Upscaler"
INI_DX12_VALUE = "dlss"
INI_LIB_SECTION = "Libraries"
INI_LIB_KEY = "NvngxPath"

MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
# nvngx.dll from the release is ~1 MB; the setup appends the network.
MIN_READY_BYTES = 2 * 1024 * 1024

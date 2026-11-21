"""Receive profiles and scan plans; the single SX1262 hears one profile at a time.

Numeric data mirrors LORA Tunnel's firmware tables (include/lora_profiles.h and
include/lora_scan.h). Those tables were derived from Meshtastic's region
definitions and default-channel slot calculation and from Kismet's LoRaPipe
channel reference and MeshCore's regional presets. No upstream code is copied.
"""

from dataclasses import asdict, dataclass, replace

# Cap LoRa-1262 (U214) usable band. Profiles whose occupied bandwidth falls
# outside it are listed but not selectable, rather than silently clamped.
HARDWARE_MIN_MHZ = 868.0
HARDWARE_MAX_MHZ = 923.0

MESHTASTIC_SYNC = 0x2B
MESHCORE_SYNC = 0x12
MIN_DWELL = 5.0
MAX_DWELL = 600.0
DEFAULT_DWELL = 30.0


@dataclass(frozen=True)
class Profile:
    id: str
    label: str
    region: str
    protocol: str
    frequency_hz: int
    bandwidth_hz: int
    spreading_factor: int
    coding_rate: int
    sync_word: int
    preamble_symbols: int
    dwell_seconds: float = DEFAULT_DWELL

    def to_dict(self):
        return asdict(self)

    @property
    def frequency_mhz(self):
        return self.frequency_hz / 1e6

    @property
    def short(self):
        """Compact operator label, e.g. 'MT LongFast' or 'MC Narrow'."""
        return ("MT " if self.protocol == "meshtastic" else "MC ") + self.label

    def selectable(self):
        return fits_hardware(self.frequency_hz, self.bandwidth_hz)


@dataclass(frozen=True)
class Region:
    code: str
    label: str
    minimum_mhz: float
    maximum_mhz: float


@dataclass(frozen=True)
class ModemPreset:
    code: str
    name: str          # Meshtastic default channel name (also its slot hash input)
    bandwidth_khz: float
    sf: int
    cr: int


REGIONS = {r.code: r for r in (
    Region("US", "US / Canada 915", 902.0, 928.0),
    Region("EU_868", "Europe 868", 869.4, 869.65),
    Region("ANZ", "Australia / NZ 915", 915.0, 928.0),
    Region("JP", "Japan 920", 920.5, 923.5),
    Region("KR", "Korea 920", 920.0, 923.0),
    Region("TW", "Taiwan 920", 920.0, 925.0),
    Region("RU", "Russia 868", 868.7, 869.2),
    Region("IN", "India 865", 865.0, 867.0),
    Region("NZ_865", "New Zealand 865", 864.0, 868.0),
    Region("TH", "Thailand 920", 920.0, 925.0),
    Region("UA_868", "Ukraine 868", 868.0, 868.6),
    Region("MY_919", "Malaysia 919", 919.0, 924.0),
    Region("SG_923", "Singapore 923", 917.0, 925.0),
    Region("PH_868", "Philippines 868", 868.0, 869.4),
    Region("PH_915", "Philippines 915", 915.0, 918.0),
    Region("KZ_863", "Kazakhstan 863", 863.0, 868.0),
    Region("NP_865", "Nepal 865", 865.0, 868.0),
    Region("BR_902", "Brazil 902", 902.0, 907.5),
)}

PRESETS = {p.code: p for p in (
    ModemPreset("LONG_FAST", "LongFast", 250, 11, 5),
    ModemPreset("LONG_TURBO", "LongTurbo", 500, 11, 8),
    ModemPreset("LONG_MODERATE", "LongMod", 125, 11, 8),
    ModemPreset("LONG_SLOW", "LongSlow", 125, 12, 8),
    ModemPreset("MEDIUM_FAST", "MediumFast", 250, 9, 5),
    ModemPreset("MEDIUM_SLOW", "MediumSlow", 250, 10, 5),
    ModemPreset("SHORT_FAST", "ShortFast", 250, 7, 5),
    ModemPreset("SHORT_SLOW", "ShortSlow", 250, 8, 5),
    ModemPreset("SHORT_TURBO", "ShortTurbo", 500, 7, 5),
)}

# (region, name, MHz, kHz, SF, CR). MeshCore preamble: 32 symbols at SF7/8,
# 16 at SF9+. "AUTO" selects the first entry for a region.
MESHCORE = (
    ("US", "US-NARROW", 910.525, 62.5, 7, 5),
    ("US", "US-SOCAL", 927.875, 62.5, 7, 5),
    ("US", "US-COSTA_RICA", 910.525, 125, 11, 5),
    ("EU_868", "EU_868-NARROW", 869.618, 62.5, 8, 8),
    ("EU_868", "EU_868-SF7", 869.618, 62.5, 7, 5),
    ("EU_868", "EU_868-CZECH", 869.432, 62.5, 7, 5),
    ("EU_868", "EU_868-LEGACY", 869.525, 250, 11, 5),
    ("EU_868", "EU_868-DEFAULT", 869.618, 62.5, 8, 5),
    ("EU_868", "EU_868-PORTUGAL", 869.618, 62.5, 7, 6),
    ("ANZ", "ANZ-DEFAULT", 915.800, 250, 10, 5),
    ("ANZ", "ANZ-NARROW", 916.575, 62.5, 7, 7),
    ("ANZ", "ANZ-MID", 915.075, 125, 9, 5),
    ("ANZ", "ANZ-SA_WA", 923.125, 62.5, 8, 8),
    ("ANZ", "ANZ-NZ_NARROW", 917.375, 62.5, 7, 5),
    ("ANZ", "ANZ-NZ_GISBORNE", 917.375, 250, 11, 5),
    ("ANZ", "ANZ-QLD", 923.125, 62.5, 8, 5),
    ("BR_902", "BR_902-DEFAULT", 923.125, 62.5, 8, 8),
)

MODES = ("meshtastic", "meshcore", "both", "survey")
MODE_LABELS = {"meshtastic": "Meshtastic", "meshcore": "MeshCore",
               "both": "Both (alternate)", "survey": "Survey (all presets)"}


def fits_hardware(frequency_hz, bandwidth_hz, minimum=HARDWARE_MIN_MHZ, maximum=HARDWARE_MAX_MHZ):
    half = bandwidth_hz / 2e6
    mhz = frequency_hz / 1e6
    return mhz - half >= minimum - 1e-6 and mhz + half <= maximum + 1e-6


def _djb2(text):
    value = 5381
    for byte in text.encode("ascii"):
        value = (value * 33 + byte) & 0xFFFFFFFF
    return value


def slot_count(region, preset):
    return int((region.maximum_mhz - region.minimum_mhz + 1e-7) // (preset.bandwidth_khz / 1000.0))


def meshtastic(region_code, preset_code="LONG_FAST", slot=0, dwell=DEFAULT_DWELL):
    """Meshtastic profile. Slot 0 selects the preset's default-channel slot."""
    region = REGIONS.get(region_code)
    preset = PRESETS.get(preset_code)
    if region is None:
        raise ValueError("Select a supported LoRa region")
    if preset is None:
        raise ValueError("Unknown Meshtastic modem preset")
    slots = slot_count(region, preset)
    if not slots or not 0 <= int(slot) <= slots:
        raise ValueError("Frequency slot is outside this region and preset")
    chosen = int(slot) or 1 + _djb2(preset.name) % slots
    mhz = region.minimum_mhz + (chosen - 0.5) * preset.bandwidth_khz / 1000.0
    return Profile(
        # Kismet LoRaPipe channel naming; an explicit slot is appended.
        id="meshtastic-%s-%s%s" % (region.code, preset.code, "-S%d" % chosen if slot else ""),
        label=preset.name, region=region.code, protocol="meshtastic",
        frequency_hz=int(round(mhz * 1e6)), bandwidth_hz=int(preset.bandwidth_khz * 1000),
        spreading_factor=preset.sf, coding_rate=preset.cr, sync_word=MESHTASTIC_SYNC,
        preamble_symbols=16, dwell_seconds=_dwell(dwell))


def meshcore_profiles(region_code):
    return [_meshcore(row) for row in MESHCORE if row[0] == region_code]


def meshcore(region_code, name="AUTO", dwell=DEFAULT_DWELL):
    """MeshCore profile; AUTO picks the first one that fits the cap's band."""
    options = meshcore_profiles(region_code)
    if name != "AUTO":
        options = [p for p in options if p.label == name or p.id.endswith(name)]
    options = [p for p in options if p.selectable()]
    if not options:
        return None
    return replace(options[0], dwell_seconds=_dwell(dwell))


def _meshcore(row):
    region, name, mhz, khz, sf, cr = row
    label = name.split("-", 1)[1].replace("_", " ").title()
    return Profile(id="meshcore-" + name, label=label, region=region, protocol="meshcore",
                   frequency_hz=int(round(mhz * 1e6)), bandwidth_hz=int(khz * 1000),
                   spreading_factor=sf, coding_rate=cr, sync_word=MESHCORE_SYNC,
                   preamble_symbols=32 if sf <= 8 else 16)


def _dwell(value):
    value = float(value)
    if not MIN_DWELL <= value <= MAX_DWELL:
        raise ValueError("Dwell must be between 5 and 600 seconds")
    return value


def scan_plan(config):
    """Return the ordered, hardware-checked profile list for a configuration.

    meshtastic/meshcore: one profile. both: alternate the two. survey: every
    Meshtastic preset's default slot plus every MeshCore profile for the region,
    so an operator can discover what a community actually uses.
    """
    region = config.get("region") or ""
    if region not in REGIONS:
        raise ValueError("Select a supported LoRa region first")
    mode = config.get("mode", "meshtastic")
    if mode not in MODES:
        raise ValueError("Unsupported scan mode")
    dwell = float(config.get("dwell_seconds", DEFAULT_DWELL))
    plan = []
    if mode in ("meshtastic", "both"):
        plan.append(meshtastic(region, config.get("preset", "LONG_FAST"),
                               int(config.get("slot", 0)), dwell))
    if mode in ("meshcore", "both"):
        profile = meshcore(region, config.get("meshcore_profile", "AUTO"), dwell)
        if profile is not None:
            plan.append(profile)
    if mode == "survey":
        survey_dwell = float(config.get("survey_dwell_seconds", 15))
        for code in PRESETS:
            try:
                plan.append(meshtastic(region, code, 0, survey_dwell))
            except ValueError:
                continue
        plan.extend(replace(p, dwell_seconds=_dwell(survey_dwell))
                    for p in meshcore_profiles(region))
    # Coding rate travels in the LoRa header, so profiles that differ only in
    # CR hear the same packets. Survey keeps one of each (Kismet does the same).
    seen, unique = set(), []
    for p in plan:
        key = (p.frequency_hz, p.bandwidth_hz, p.spreading_factor, p.sync_word)
        if mode == "survey" and key in seen:
            continue
        seen.add(key)
        unique.append(p)
    plan = [p for p in unique if p.selectable()]
    if not plan:
        raise ValueError("No receive profile for this region fits the cap's 868-923 MHz band")
    return plan


def from_dict(data):
    """Rebuild a Profile from a stored snapshot (used by tests and readback)."""
    fields = {k: data[k] for k in Profile.__dataclass_fields__ if k in data}
    return Profile(**fields)


_BANDWIDTHS = {62500, 125000, 250000, 500000}


def validate_profile(profile):
    """Reject anything the radio drivers should not be asked to tune."""
    if not isinstance(profile, Profile):
        raise ValueError("Use a receive profile")
    if (profile.bandwidth_hz not in _BANDWIDTHS or not 5 <= profile.spreading_factor <= 12
            or not 5 <= profile.coding_rate <= 8 or not 0 <= profile.sync_word <= 255
            or not 6 <= profile.preamble_symbols <= 65535 or not profile.selectable()):
        raise ValueError("Profile is outside the cap's supported receive settings")
    return profile

"""Download the pinned PlantUML jar used by MdFlow."""
import hashlib
from pathlib import Path
from urllib.request import urlopen

VERSION = "1.2026.6"
URL = f"https://github.com/plantuml/plantuml/releases/download/v{VERSION}/plantuml-{VERSION}.jar"
SHA256 = "89948f14c93756c7a3fb7b69078ff37e8489fd79dd430c582b931e2f65358690"
DEST = Path(__file__).parents[1] / "mdflow" / "resources" / "vendor" / "plantuml" / "plantuml.jar"


def main() -> None:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading PlantUML {VERSION} ...")
    with urlopen(URL, timeout=60) as response:  # noqa: S310 - fixed trusted URL
        data = response.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual != SHA256:
        raise RuntimeError(f"PlantUML checksum mismatch: expected {SHA256}, got {actual}")
    DEST.write_bytes(data)
    print(f"Saved: {DEST}")


if __name__ == "__main__":
    main()

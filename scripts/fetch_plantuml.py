"""Download the pinned PlantUML jar used by MdFlow."""
from pathlib import Path
from urllib.request import urlopen

VERSION = "1.2026.6"
URL = f"https://github.com/plantuml/plantuml/releases/download/v{VERSION}/plantuml-{VERSION}.jar"
DEST = Path(__file__).parents[1] / "mdflow" / "resources" / "vendor" / "plantuml" / "plantuml.jar"


def main() -> None:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading PlantUML {VERSION} ...")
    with urlopen(URL, timeout=60) as response:  # noqa: S310 - fixed trusted URL
        DEST.write_bytes(response.read())
    print(f"Saved: {DEST}")


if __name__ == "__main__":
    main()

# resources

- `mermaid.min.js` … このディレクトリに配置する（Git管理外）。
  初回のみ `python scripts/fetch_mermaid.py` を実行して取得する。
- `vendor/plantuml/plantuml.jar` … PlantUML を使う場合に配置する（Git管理外）。
  初回のみ `python scripts/fetch_plantuml.py` を実行して取得する。別の JAR は
  `MDFLOW_PLANTUML_JAR` でも指定できる。
- `vendor/monaco/vs/` … Monaco Editor本体（Git管理外）。
  初回のみ `python scripts/fetch_monaco.py` を実行して取得する。
  取得後、アプリは実行中に外部通信を一切行わない。

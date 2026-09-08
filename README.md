# MdFlow

Word/Excel/PPT に散らばる仕様書を **Markdown に統一**し、埋め込んだ **Mermaid フローチャートを
条件に応じて動的にハイライト**するローカルデスクトップアプリ。
さらに **PPT へのスマート出力／PPT からの完全復元**（双方向）を備える。

## 設計（採用した推奨構成）

| 項目 | 決定 | 理由 |
|---|---|---|
| UI | **QWebEngine + QWebChannel の単一ページWeb UI**（サーバ不要）。NoteWithPixie 風ダークテーマ（`#1e1e2a`/アクセント`#8b7cff`・`#5ad1c9`）、markdown-it + mermaid をローカル同梱 | ローカルデスクトップ要件を保ちつつ、洗練されたIDE風UIを再現 |
| 表示 | Mermaid.js（`securityLevel='strict'`, `theme:'dark'`） | 完全ローカル・スクリプト実行を遮断 |
| 画像化 | 表示は **SVG**、PPT貼付は **PNG grab** | 追加依存ゼロ・Node/Chromium不要 |
| 条件定義 | 本文中の ` ```mdflow-mapping ` ブロック（図ごと） | 可読・grep可能・差分が見やすい |
| 選択状態 | **Frontmatter を単一ソースの正**（`conditions.json` は不採用） | 1ファイル自己完結・二重管理のズレを防ぐ |
| PPT埋込 | **カスタムパート（主）＋ノート（副）＋Alt Text（参考）** の三重化 | 画像差し替えでも消えにくい／PowerPoint保存でも確実 |
| 整合性 | ペイロードに mermaid の **sha256** を持たせ復元時に照合 | 画像とコードのズレを検知して警告 |

ペイロード形式: `MDFLOW:v1:<base64(gzip(json))>`（grep可能・バージョン識別・決定的出力）。

## セットアップ

```bash
pip install -r requirements.txt
python scripts/fetch_mermaid.py        # 初回のみ（以降オフライン）
python scripts/fetch_markdown_it.py    # 初回のみ（以降オフライン）
python scripts/fetch_monaco.py         # 初回のみ（以降オフライン）
```

PlantUML も使用する場合は Java ランタイムをインストールして、JAR を取得します。

```bash
python scripts/fetch_plantuml.py       # 初回のみ（以降オフライン）
```

Windows では、Java のインストールも含めて PowerShell からセットアップできます。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_plantuml_windows.ps1
```

このスクリプトは winget で Eclipse Temurin 21 JRE を導入した後、固定バージョンの
PlantUML JAR を `mdflow/resources/vendor/plantuml/` に取得します。

`plantuml` コマンドが PATH にある場合はそちらを優先します。任意の実行ファイルや
JAR を使う場合は、それぞれ `MDFLOW_PLANTUML`、`MDFLOW_PLANTUML_JAR` で指定できます。

GUI は PyQt6（`PyQt6 + PyQt6-WebEngine`）または PyQt5（`PyQt5 + PyQtWebEngine`）のどちらでも動く。
ベンダーJS（mermaid / markdown-it）は `mdflow/resources/vendor/` に配置され、実行中は外部通信しない。
エディタは現状 textarea ベース（ダークIDE風にスタイル済み・Monaco 差し替え余地あり）。

## 使い方

```bash
python -m mdflow                    # GUI 起動（左:エディタ / 右:プレビュー＋条件JSON）
```

- 図・プリセットをツールバーで切替、または「条件(JSON)」を編集すると即座に再描画。
- 「PPTへ出力」でコード＋条件を内包した1枚スライドを生成。
- 「PPT取込」またはウィンドウへ **.pptx をドラッグ＆ドロップ**でコード・条件・ハイライトを復元。

### ヘッドレス CLI（PyQt不要・CI向け）

```bash
# PPT から復元・検査（hash不一致なら exit 2）
python -m mdflow.cli import out.pptx

# 画像を指定して PPT 生成
python -m mdflow.cli export samples/login.md \
    --diagram flow-login --image fig.png -o out.pptx \
    --conditions '{"role":"admin","error_count":0}'
```

## Markdown の書き方

```markdown
​```mermaid
%% id: flow-login
flowchart TD
    A[開始] --> B{認証情報あり?}
    ...
​```

​```mdflow-mapping
diagram: flow-login
presets:
  管理者・正常:
    when: 'role == "admin" && error_count == 0'
    active_nodes: [A, B, C, D, G]
style:
  active: 'fill:#ff9999,stroke:#333,stroke-width:2px'
​```
```

PlantUML は `plantuml`（または `puml`）フェンスで記述するとプレビューされます。

```markdown
​```plantuml
@startuml
Alice -> Bob: Hello
Bob --> Alice: Hi
@enduml
​```
```

PlantUML の描画はローカルプロセスで行われ、ソースが外部サービスへ送信されることはありません。

## MonacoエディタとローカルLLM

編集画面はMonaco Editorを使用し、Markdown、Mermaid、PlantUMLの強調表示と補完、見出し・図の
アウトライン、検索・置換、Undo、`Ctrl+S`、プレビューとのスクロール同期を提供します。プレビューの
図はズーム、SVG/PNGコピー、SVG保存ができます。

ローカルLLMは標準でOllama（`http://127.0.0.1:11434`）へ接続します。Windowsでは次のスクリプトで
Ollamaをインストールできます。モデル名を指定するとモデルも取得します。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_local_llm_windows.ps1 -Model "使用するモデル名"
```

ツールバーの「Local LLM」から、選択範囲または文書全体について理由を質問したり、編集案を生成して
Undo可能な状態で適用できます。LM StudioなどのOpenAI互換ローカルサーバーを使う場合は次の環境変数を
設定します。

接続方式・URL・タイムアウトは画面内でも設定でき、ブラウザのローカルストレージへ保存されます。
用途ごとに選んだモデルも記憶されます。応答はストリーミング表示され、「生成停止」で中断できます。
編集案はMonaco Diff Editorで比較・調整でき、適用前にコードフェンス、図ID重複、Mermaid、PlantUMLの
構文を検査します。送信範囲は「選択範囲」「現在の見出し」「文書全体」から選択でき、概算トークン数も
表示されます。

```powershell
$env:MDFLOW_LLM_PROVIDER = "openai"
$env:MDFLOW_LLM_URL = "http://127.0.0.1:1234/v1"
$env:MDFLOW_LLM_MODEL = "ローカルモデル名"
```

- ルール式は `&& || ! == != < <= > >=` に対応（`eval` 不使用の安全な AST 評価）。
- 未定義の識別子は `None` として扱い、比較は例外にせず False に倒す。
- ノードIDの実在を検証し、存在しないIDへの指定はプレビューに警告表示。

## 構成

```
mdflow/
  payload.py     ペイロードのencode/decode＋hash整合
  mapping.py     mdflow-mapping パース＋安全なルール評価
  mermaid.py     ブロック抽出・ノードID解析・非破壊スタイル注入
  frontmatter.py 選択状態（正）の読み書き
  document.py    統合ロジック（GUI/CLI/テスト共通・PyQt非依存）
  webapi.py      フロントに返すJSONを組む純ロジック（PyQt非依存・テスト可能）
  preview.py     静的HTML生成（サーバレス出力用の補助）
  pptx_io.py     PPT出力／取込（三重埋め込み・フォールバック）
  app.py         QWebEngine ホスト（QWebChannel でBridge登録）
  app_bridge.py  ui.js から呼ばれる QWebChannel スロット群（ダイアログ等の副作用）
  cli.py         ヘッドレスCLI
  resources/     ui.html / ui.css / ui.js（Web UI）, vendor/（同梱JS）
tests/           コア・PPT往復・プレビュー・webapi のテスト（27件）
```

## テスト

```bash
python -m pytest tests/ -q
```

`md → ppt → md` のラウンドトリップ、ノート系フォールバック、hash改変検知を含む。

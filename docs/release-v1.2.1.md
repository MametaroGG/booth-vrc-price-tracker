# Boopa v1.2.1


## 変更点

- 拡張機能の表示名を、全言語で「Boopa – BOOTH Price Tracker for VRChat」に統一しました。これまでは言語ごとに異なる名前（日本語では「Boopa - BOOTHのVRChat向け価格トラッカー」など）になっていました。説明文は各言語のままです。


## 配布ファイル

`boopa-v1.2.1-chrome-web-store.zip` は、manifest.jsonを直下に配置したChrome Web Store提出用パッケージです。手動で試す場合は展開し、Chromeの拡張機能画面から「パッケージ化されていない拡張機能を読み込む」で読み込めます。


## 検証

- manifestの国際化テスト3件に合格（バージョン整合、5言語のメッセージ参照と文字数制限を含む）

- ZIP内の全実行ファイル・アイコン・5言語のメッセージ参照、JavaScript構文、ソースとの一致を確認

- 実際のChromeへインストールした状態での画面確認は未実施


SHA-256: `7c21c461e3fe3155a46fad38612fb917db1abfdc417b65c62c6c5fe608a18108`

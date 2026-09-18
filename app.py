import time
import io

import streamlit as st
import requests
import pandas as pd


# =========================================================
# 基本設定
# =========================================================

start_time = time.time()

st.set_page_config(
    page_title="未解明出来高レーダー",
    page_icon="📡",
    layout="wide",
)

st.title("📡 未解明出来高レーダー Ver.1")
st.subheader("普段と違う出来高を検知する観測装置")

st.info(
    "出来高の異常だけを検知します。"
    "株価上昇・RSI・MACD・ニュース・材料などは判定条件に含めません。"
)

JQUANTS_API_KEY = st.secrets["JQUANTS_API_KEY"]

headers = {
    "x-api-key": JQUANTS_API_KEY
}


# =========================================================
# サイドバー
# =========================================================

st.sidebar.header("📡 表示設定")

min_trading_value = st.sidebar.number_input(
    "最低20日平均売買代金（億円）",
    min_value=0.0,
    value=1.0,
    step=0.5,
)

display_count = st.sidebar.slider(
    "ランキング表示件数",
    min_value=10,
    max_value=200,
    value=50,
    step=10,
)

st.sidebar.caption(
    "Ver.1では倍率による強制除外はしません。"
    "まず実際に何が上位へ出てくるか観察します。"
)


# =========================================================
# 銘柄マスター取得
# =========================================================

st.write("📡 銘柄マスター取得中...")

master_url = "https://api.jquants.com/v2/equities/master"

master_response = requests.get(
    master_url,
    headers=headers,
    timeout=30,
)

if master_response.status_code != 200:
    st.error(
        f"銘柄マスター取得エラー："
        f"{master_response.status_code}"
    )
    st.stop()

master_data = master_response.json().get("data", [])

if not master_data:
    st.error("銘柄マスターが空です。")
    st.stop()

master_df = pd.DataFrame(master_data)

name_map_df = master_df[
    ["Code", "CoName"]
].copy()

name_map_df["Code"] = (
    name_map_df["Code"]
    .astype(str)
    .str.zfill(5)
)

# 東証内国株式
auto_codes = (
    master_df.loc[
        master_df["ProdCat"] == "011",
        "Code"
    ]
    .astype(str)
    .str.zfill(5)
    .tolist()
)

auto_code_set = set(auto_codes)

st.success(
    f"銘柄マスター取得完了："
    f"{len(auto_codes):,}銘柄"
)


# =========================================================
# Bulk一覧取得
# =========================================================

st.write("📡 J-Quants Bulk一覧取得中...")

bulk_list_url = "https://api.jquants.com/v2/bulk/list"

bulk_response = requests.get(
    bulk_list_url,
    headers=headers,
    params={
        "endpoint": "/equities/bars/daily"
    },
    timeout=30,
)

if bulk_response.status_code != 200:
    st.error(
        f"Bulk一覧取得エラー："
        f"{bulk_response.status_code}"
    )
    st.stop()

bulk_data = bulk_response.json()

bulk_files = bulk_data.get("data", [])

if not bulk_files:
    st.error("Bulkファイル一覧が取得できませんでした。")
    st.stop()


# =========================================================
# Historical / Live 分離
# =========================================================

live_bulk_files = [
    item
    for item in bulk_files
    if "/live/" in item.get("Key", "")
]

historical_bulk_files = [
    item
    for item in bulk_files
    if "/historical/" in item.get("Key", "")
]

if not live_bulk_files and not historical_bulk_files:
    st.error("利用可能なBulkファイルがありません。")
    st.stop()


# =========================================================
# 75日平均用データ
#
# 75営業日を確実に確保したいので、
# historicalを多めに取得します。
#
# 既存🐢では historical直近3ファイルでしたが、
# Ver.1では余裕を持たせて直近6ファイルを使用。
# =========================================================

recent_historical_files = historical_bulk_files[-6:]

bulk_target_files = (
    recent_historical_files
    + live_bulk_files
)

# Key重複があれば除去
unique_files = {}

for item in bulk_target_files:
    key = item.get("Key")

    if key:
        unique_files[key] = item

bulk_target_files = list(unique_files.values())

st.write(
    f"📦 読み込み対象Bulk："
    f"{len(bulk_target_files)}ファイル"
)


# =========================================================
# Bulkデータ取得
# =========================================================

bulk_get_url = "https://api.jquants.com/v2/bulk/get"

bulk_dfs = []

progress_bar = st.progress(0)

status_text = st.empty()

total_files = len(bulk_target_files)

for i, bulk_item in enumerate(bulk_target_files):

    item_key = bulk_item["Key"]

    status_text.write(
        f"📥 データ取得中 "
        f"{i + 1}/{total_files}"
    )

    item_get_response = requests.get(
        bulk_get_url,
        headers=headers,
        params={
            "key": item_key
        },
        timeout=30,
    )

    if item_get_response.status_code != 200:
        st.warning(
            f"取得失敗：{item_key}"
        )
        continue

    item_get_data = item_get_response.json()

    item_download_url = item_get_data.get("url")

    if not item_download_url:
        st.warning(
            f"Download URLなし：{item_key}"
        )
        continue

    item_file_response = requests.get(
        item_download_url,
        timeout=60,
    )

    if item_file_response.status_code != 200:
        st.warning(
            f"ファイルDL失敗：{item_key}"
        )
        continue

    try:

        item_df = pd.read_csv(
            io.BytesIO(
                item_file_response.content
            ),
            compression="gzip",
            usecols=[
                "Date",
                "Code",
                "C",
                "Vo",
            ],
            dtype={
                "Code": str
            },
        )

        bulk_dfs.append(item_df)

    except Exception as e:

        st.warning(
            f"CSV読込失敗："
            f"{item_key} / {e}"
        )

    progress_bar.progress(
        (i + 1) / total_files
    )


progress_bar.empty()
status_text.empty()

if not bulk_dfs:
    st.error(
        "日足データを取得できませんでした。"
    )
    st.stop()


# =========================================================
# 全Bulk結合
# =========================================================

st.write("📡 日足データ結合中...")

bulk_all_df = pd.concat(
    bulk_dfs,
    ignore_index=True,
)

bulk_all_df["Code"] = (
    bulk_all_df["Code"]
    .astype(str)
    .str.zfill(5)
)

bulk_all_df = bulk_all_df[
    bulk_all_df["Code"].isin(
        auto_code_set
    )
].copy()

bulk_all_df["Date"] = pd.to_datetime(
    bulk_all_df["Date"],
    errors="coerce",
)

bulk_all_df["C"] = pd.to_numeric(
    bulk_all_df["C"],
    errors="coerce",
)

bulk_all_df["Vo"] = pd.to_numeric(
    bulk_all_df["Vo"],
    errors="coerce",
)

bulk_all_df = bulk_all_df.dropna(
    subset=[
        "Code",
        "Date",
        "C",
        "Vo",
    ]
)

# HistoricalとLiveで同一日が重複した場合に備える
bulk_all_df = bulk_all_df.drop_duplicates(
    subset=[
        "Code",
        "Date",
    ],
    keep="last",
)

bulk_all_df = bulk_all_df.sort_values(
    [
        "Code",
        "Date",
    ]
).reset_index(drop=True)


# =========================================================
# 出来高計算
#
# shift(1) が重要。
# 今日の出来高を平均値の計算に含めない。
# =========================================================

st.write("🧮 出来高異常計算中...")

volume_group = bulk_all_df.groupby(
    "Code"
)["Vo"]

bulk_all_df["Vol5"] = (
    volume_group.transform(
        lambda x:
        x.shift(1)
        .rolling(
            5,
            min_periods=5
        )
        .mean()
    )
)

bulk_all_df["Vol10"] = (
    volume_group.transform(
        lambda x:
        x.shift(1)
        .rolling(
            10,
            min_periods=10
        )
        .mean()
    )
)

bulk_all_df["Vol20"] = (
    volume_group.transform(
        lambda x:
        x.shift(1)
        .rolling(
            20,
            min_periods=20
        )
        .mean()
    )
)

bulk_all_df["Vol25"] = (
    volume_group.transform(
        lambda x:
        x.shift(1)
        .rolling(
            25,
            min_periods=25
        )
        .mean()
    )
)

bulk_all_df["Vol75"] = (
    volume_group.transform(
        lambda x:
        x.shift(1)
        .rolling(
            75,
            min_periods=75
        )
        .mean()
    )
)


# =========================================================
# 3種類の出来高倍率
# =========================================================

# 今日だけ突然おかしいか
bulk_all_df["InstantRatio"] = (
    bulk_all_df["Vo"]
    / bulk_all_df["Vol25"]
)

# 最近5日間の出来高水準
bulk_all_df["ShortRatio"] = (
    bulk_all_df["Vol5"]
    / bulk_all_df["Vol25"]
)

# 最近10日間と長期75日の比較
bulk_all_df["MediumRatio"] = (
    bulk_all_df["Vol10"]
    / bulk_all_df["Vol75"]
)


# =========================================================
# 平均売買代金
# =========================================================

# Ver.1では簡易的に
# 終値 × 20日平均出来高
bulk_all_df["AvgTradingValue20"] = (
    bulk_all_df["C"]
    * bulk_all_df["Vol20"]
)


# =========================================================
# 最新日抽出
# =========================================================

latest_date = bulk_all_df[
    "Date"
].max()

latest_df = bulk_all_df[
    bulk_all_df["Date"]
    == latest_date
].copy()

# 75日平均が計算できる銘柄のみ
latest_df = latest_df.dropna(
    subset=[
        "Vol25",
        "Vol75",
        "InstantRatio",
        "ShortRatio",
        "MediumRatio",
    ]
)


# =========================================================
# 銘柄名追加
# =========================================================

latest_df = latest_df.merge(
    name_map_df,
    on="Code",
    how="left",
)


# =========================================================
# 流動性フィルター
# =========================================================

min_trading_value_yen = (
    min_trading_value
    * 100_000_000
)

latest_df = latest_df[
    latest_df[
        "AvgTradingValue20"
    ] >= min_trading_value_yen
].copy()


# =========================================================
# 表示用データ
# =========================================================

radar_df = latest_df[
    [
        "Code",
        "CoName",
        "C",
        "Vo",
        "Vol25",
        "Vol75",
        "InstantRatio",
        "ShortRatio",
        "MediumRatio",
        "AvgTradingValue20",
    ]
].copy()

radar_df[
    "AvgTradingValue20"
] = (
    radar_df[
        "AvgTradingValue20"
    ]
    / 100_000_000
)

radar_df = radar_df.rename(
    columns={
        "Code":
            "銘柄コード",

        "CoName":
            "銘柄名",

        "C":
            "終値",

        "Vo":
            "最新出来高",

        "Vol25":
            "25日平均出来高",

        "Vol75":
            "75日平均出来高",

        "InstantRatio":
            "瞬間倍率",

        "ShortRatio":
            "短期倍率",

        "MediumRatio":
            "中期倍率",

        "AvgTradingValue20":
            "20日平均売買代金(億円)",
    }
)

radar_df = radar_df.round(
    {
        "終値": 1,
        "25日平均出来高": 0,
        "75日平均出来高": 0,
        "瞬間倍率": 2,
        "短期倍率": 2,
        "中期倍率": 2,
        "20日平均売買代金(億円)": 2,
    }
)


# =========================================================
# メイン画面
# =========================================================

st.divider()

st.header("📡 未解明出来高レーダー")

st.write(
    "📅 最新取引日：",
    latest_date.date()
)

st.write(
    "🔎 観測対象銘柄数：",
    len(radar_df)
)

st.caption(
    "倍率が高い＝買いではありません。"
    "通常と異なる売買が発生している可能性を"
    "探すための観測値です。"
)


# =========================================================
# 瞬間異常ランキング
# =========================================================

st.subheader(
    "⚡ 1. 瞬間出来高ランキング"
)

st.caption(
    "当日出来高 ÷ 過去25日平均出来高"
)

instant_df = (
    radar_df
    .sort_values(
        "瞬間倍率",
        ascending=False
    )
    .head(display_count)
    .reset_index(drop=True)
)

instant_df.index = (
    instant_df.index + 1
)

st.dataframe(
    instant_df,
    use_container_width=True,
)


# =========================================================
# 短期変化ランキング
# =========================================================

st.subheader(
    "👀 2. 短期出来高変化ランキング"
)

st.caption(
    "過去5日平均出来高 ÷ "
    "過去25日平均出来高"
)

short_df = (
    radar_df
    .sort_values(
        "短期倍率",
        ascending=False
    )
    .head(display_count)
    .reset_index(drop=True)
)

short_df.index = (
    short_df.index + 1
)

st.dataframe(
    short_df,
    use_container_width=True,
)


# =========================================================
# 中期変化ランキング
# =========================================================

st.subheader(
    "👽 3. 中期出来高変化ランキング"
)

st.caption(
    "過去10日平均出来高 ÷ "
    "過去75日平均出来高"
)

medium_df = (
    radar_df
    .sort_values(
        "中期倍率",
        ascending=False
    )
    .head(display_count)
    .reset_index(drop=True)
)

medium_df.index = (
    medium_df.index + 1
)

st.dataframe(
    medium_df,
    use_container_width=True,
)


# =========================================================
# 3指標をまとめて観察
#
# Ver.1ではScore化しない。
# =========================================================

st.subheader(
    "📖 4. 総合観測テーブル"
)

st.caption(
    "Score化せず、3種類の出来高倍率を"
    "そのまま観察します。"
)

observation_df = (
    radar_df
    .sort_values(
        [
            "瞬間倍率",
            "短期倍率",
            "中期倍率",
        ],
        ascending=[
            False,
            False,
            False,
        ],
    )
    .head(display_count)
    .reset_index(drop=True)
)

observation_df.index = (
    observation_df.index + 1
)

st.dataframe(
    observation_df,
    use_container_width=True,
)


# =========================================================
# 個別銘柄確認
# =========================================================

st.divider()

st.header("🔎 個別銘柄確認")

check_code = st.text_input(
    "銘柄コード",
    placeholder="例：5574 / 8848"
)

if check_code:

    check_code = (
        str(check_code)
        .strip()
    )

    # 4桁入力ならJ-Quants形式へ
    if len(check_code) == 4:
        check_code = (
            check_code + "0"
        )

    stock_history = bulk_all_df[
        bulk_all_df["Code"]
        == check_code
    ].copy()

    if stock_history.empty:

        st.warning(
            "対象銘柄が見つかりません。"
        )

    else:

        company_name = (
            name_map_df.loc[
                name_map_df["Code"]
                == check_code,
                "CoName"
            ]
        )

        if not company_name.empty:
            st.subheader(
                f"{check_code[:4]} "
                f"{company_name.iloc[0]}"
            )

        history_display = stock_history[
            [
                "Date",
                "C",
                "Vo",
                "Vol25",
                "Vol75",
                "InstantRatio",
                "ShortRatio",
                "MediumRatio",
            ]
        ].copy()

        history_display = (
            history_display
            .sort_values(
                "Date",
                ascending=False
            )
            .head(30)
        )

        history_display = history_display.rename(
            columns={
                "Date":
                    "日付",

                "C":
                    "終値",

                "Vo":
                    "出来高",

                "Vol25":
                    "25日平均出来高",

                "Vol75":
                    "75日平均出来高",

                "InstantRatio":
                    "瞬間倍率",

                "ShortRatio":
                    "短期倍率",

                "MediumRatio":
                    "中期倍率",
            }
        )

        history_display = history_display.round(
            {
                "終値": 1,
                "25日平均出来高": 0,
                "75日平均出来高": 0,
                "瞬間倍率": 2,
                "短期倍率": 2,
                "中期倍率": 2,
            }
        )

        st.dataframe(
            history_display,
            use_container_width=True,
        )


# =========================================================
# 実行時間
# =========================================================

elapsed_time = (
    time.time()
    - start_time
)

st.divider()

st.caption(
    f"⏱️ 実行時間："
    f"{elapsed_time:.1f}秒"
)

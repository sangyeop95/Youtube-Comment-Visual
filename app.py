import plotly.express as px
from dotenv import load_dotenv
import os

from func import *

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")


# ===================== UI 기본 설정 =====================
st.set_page_config(
    page_title="YouTube 댓글 분석",
    page_icon="🎬",
    layout="wide"
)
st.title("🎬 YouTube 댓글 분석 대시보드")

with st.expander("ℹ️ 사용방법", expanded=True):
    st.markdown(
    """
    1. 댓글 분석할 **유튜브 영상 URL**을 입력하세요.
    2. **분석 시작**을 누르면 댓글/대댓글을 수집하고 단어 빈도 그래프와 좋아요 상위 댓글을 보여줍니다.
    3. **페이지 수**는 분석할 댓글의 수를 의미합니다. (1페이지당 100개의 댓글 분석)
    4. **키워드 수**를 조절하여 댓글에 자주 언급된 키워드를 볼 수 있습니다.  
    
    ***Tip!*** 분석 전 아래 체크리스트를 확인하세요.
    - 영상이 댓글을 허용하는지 확인하세요.
    - 쿼터 초과 시 오류가 날 수 있어요.
    """
    )


# ===================== 사이드바 =====================
with st.sidebar:
    st.header("⚙️ 설정")
    video_url = st.text_input("유튜브 영상 URL", placeholder="https://www.youtube.com/watch?v=...")
    max_pages = st.number_input("페이지 수", min_value=1, step=1, value=10)
    fetch_all = st.checkbox("모든 페이지 댓글 분석", value=True)
    like_comment_num = st.slider("좋아요 댓글 수", 10, 100, 33, 5)
    top_n = st.slider("키워드 수", 10, 30, 20, 1)
    use_ko = st.checkbox("한국어 포함", value=True)
    use_en = st.checkbox("영어 포함", value=True)
    st.divider()
    st.subheader("불용어 추가하기")
    extra_stop = st.text_area("쉼표나 줄바꿈으로 구분", placeholder="예) 너무, 그냥, the, and")


# ===================== 실행 영역 =====================
c1, c2 = st.columns([1, 1])

with c1:
    run = st.button("분석 시작", type="primary", width="content", )
with c2:
    st.text("")

if run:
    if not video_url:
        st.warning("분석할 유튜브 영상 URL을 입력해주세요.")
        st.stop()

    try:
        video_id = extract_video_id(video_url)
    except Exception as e:
        st.error(f"""유튜브 영상 URL이 올바르지 않습니다. URL을 다시 입력해주세요.""")
        st.stop()

    with st.spinner("댓글 수집 중..."):
        try:
            max_page_value = None if fetch_all else max_pages
            records = fetch_all_comments(video_id, YOUTUBE_API_KEY, max_pages=max_page_value)
        except Exception as e:
            st.error(f"유튜브 영상 URL만 가능합니다.")
            st.stop()


    st.divider()  # -----------------------------------------


    if not records:
        st.warning("가져온 댓글이 없습니다. (댓글 비활성/제한 가능)")
        st.stop()

    video = fetch_video_and_channel(video_id)
    video_views = f"{int(video['view_count']):,}"
    video_likes = f"{int(video['like_count']):,}" if video["like_count"] is not None else "비공개/없음"
    df = pd.DataFrame(records)
    df["like_count"] = pd.to_numeric(df["like_count"])

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("총 댓글 수", f'{len(df):,}')
    col2.metric("댓글 수(최상위)", f'{(~df["is_reply"]).sum():,}')
    col3.metric("대댓글 수", f'{(df["is_reply"]).sum():,}')
    col4.metric("댓글 좋아요 수", f'{int(df["like_count"].sum()):,}')
    col5.metric("영상 좋아요 수", video_likes)


    st.divider() # -----------------------------------------


    left, right = st.columns([6, 1])
    with left:
        st.image(video["thumbnail"]["maxres"], width="content")

    with right:
        st.image(video['ch_icon_thumbnail']['high'], width=120)
        st.markdown(f"## {video['channel_title']}")
        st.metric("조회수", video_views)
        st.metric("좋아요", video_likes)

    st.markdown(f"# {video['video_title']}")
    st.write(f"{(video['published_at'])}")

    # 왼쪽: 키워드 / 오른쪽: 좋아요 차트
    left, right = st.columns([1.2, 1])
    extra_sw = parse_extra_stopwords(extra_stop)

    with left:
        st.subheader("📊 한눈에 보는 키워드 차트")
        freq = build_frequency(df,
                               use_ko=use_ko,
                               use_en=use_en,
                               tokenizer="okt",
                               pos_keep=("Noun","Adjective"),
                               extra_sw=extra_sw)
        if not freq:
            st.info("생성된 단어가 없습니다.")
        else:
            top = freq.most_common(top_n)
            words, counts = zip(*top)
            freq_df = pd.DataFrame({"word": words, "count": counts})

            fig = px.bar(freq_df,
                         x="word",
                         y="count",
                         title=f"TOP{top_n} 키워드",
                         custom_data=["word", "count"])
            fig.update_xaxes(title_text="", tickangle=-35)
            fig.update_yaxes(title_text="")
            fig.update_layout(height=600)
            fig.update_traces(
                hovertemplate=(
                    "키워드: <b>%{x}</b><br>"
                    "언급된 횟수: <b>%{y:,d}</b><br>"
                )
            )
            config = {"width": "content"}
            st.plotly_chart(fig, config=config)

            st.markdown("**자주 언급된 키워드들**")
            options = sorted(FONT_LIST.keys())
            default_font = "카페24 빛나는별"
            @st.fragment
            def show_wordcloud():
                select_font = st.selectbox("글꼴", 
                                           options,
                                           index=options.index(default_font),
                                           label_visibility="collapsed")
                select_font_path = FONT_LIST[select_font]
                wc_img = make_wordcloud_image(dict(freq), font_path=select_font_path)
                if wc_img is not None:
                    st.image(wc_img, width="content")
                else:
                    st.caption("만들 수 있는 단어가 부족합니다.")
            show_wordcloud()

    with right:
        st.subheader(f"❤️ TOP{like_comment_num} 좋아요 댓글 차트")
        mask = df["is_reply"]
        df.loc[mask, "text"] = "<대댓글> " + df.loc[mask, "text"]
        df = df[["like_count", "text", "author", "updated_at"]]
        df.rename(columns={
                "like_count": "좋아요",
                "text": "댓글",
                "author": "작성자",
                "updated_at": "작성시각"
        }, inplace=True)
        df = df.sort_values("좋아요", ascending=False).head(like_comment_num)
        df.index = pd.RangeIndex(1, len(df)+1)

        st.dataframe(df, width="content", height=1200)
        # st.table(df)
        st.caption("※ 댓글은 시간 경과에 따라 좋아요가 늦게 반영되거나 0으로 보일 수 있습니다.")
else:
    st.info("왼쪽 사이드바에서 영상 URL을 입력한 뒤 **분석 시작**을 눌러주세요.")
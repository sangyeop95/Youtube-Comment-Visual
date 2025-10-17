import pandas as pd
import re
import time
import streamlit as st
from collections import Counter
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from zoneinfo import ZoneInfo
from googleapiclient.discovery import build
from wordcloud import WordCloud

# ===================== 상수/불용어 =====================
STOPWORDS_KR = {
    "그리고","그러나","하지만","저희","저는","제가","근데","정말","진짜","그냥","이거","저거",
    "같아요","너무","정도","그","이","저","것","그건","또","하면","하는","했다","하는데",
    "합니다","에서","으로","에게","보다","까지","뭔가","하다","꾸다","같다","있다","가다",
    "않다","아니다","없다","나오다","되다","오다","자다","이다","받다","들다","보고","여기",
    "알다","맞다","많다","존나","있는","이게"
}
STOPWORDS_EN = {
    "the","a","an","and","or","but","if","in","on","at","to","for","of","with","is","are","it","this",
    "that","i","you","he","she","they","we","me","my","your","our","their","so","just","really"
}
PART_OF_SPEECH = ("Noun","Adjective","Verb") # 명사, 형용사, 동사 허용

def parse_extra_stopwords(text):
    """추가적으로 불용어를 추가할게 있을 경우 함수 사용"""
    if not text.strip():
        return set()
    items = [t.strip().lower() for t in text.split(",")]
    return set([t for t in items if t])

def extract_video_id(url: str) -> str:
    """
    유튜브 비디오, 쇼츠, 단축 도메인(youtu.be) 링크에서
    비디오 아이디 추출 반환 
    비디오 아이디는 11자로 구성되있음
    """
    parsed = urlparse(url) # url을 scheme, netloc, path, params, query 구조로 단위로 나눔
    if parsed.netloc in ("www.youtube.com", "youtube.com"):
        qs = parse_qs(parsed.query) # 파라미터를 딕셔너리 형태(키: 값)로 바꿈
        if "v" in qs: # 영상에서 id추출 -> watch?v="videoid"
            if len(qs["v"][0]) != 11:
                raise Exception
            return qs["v"][0]

        m = re.search(r"/shorts/([A-Za-z0-9_\-]+)", parsed.path) # 쇼츠에서 id추출 -> /shorts/"videoid"
        if m:
            if len(m.group(1)) != 11:
                raise Exception
            return m.group(1)

    if parsed.netloc in ("youtu.be",): # 유튜브 단축 도메인에서 id추출 -> youtu.be/"videoid"
        if len(parsed.path.strip("/")) != 11:
            raise Exception
        return parsed.path.strip("/")

    m = re.search(r"([A-Za-z0-9_\-]{11})", url) # 그 외 형태의 링크일경우 id로 추측되는 값 정규식으로 추출
    if not m:
        raise Exception
    return m.group(1)

def time_conversion(time: str):
    """기존 UTC시간을 한국시간으로 변환후 년월일:시분 형태로 변환"""
    t = time.replace("Z", "+00:00")
    t = datetime.fromisoformat(t)
    t = t.astimezone(ZoneInfo("Asia/Seoul"))
    t = t.strftime("%Y-%m-%d %H:%M")
    return t

def fetch_video_and_channel(video_id: str) -> dict:
    """
    영상 정보 & 채널 정보 반환
    영상 정보: 썸네일, 제목, 채널이름, 게시일, 조회수
    채널 정보: 채널 아이콘 썸네일
    """
    youtube = build(serviceName="youtube", version="v3", developerKey="AIzaSyAtJHZyr1IwUsBRQCo0U4NdsGx9-_ipJVY")

    video_info = []

    v_req = youtube.videos().list(
        part="snippet,statistics",
        id=video_id
    ).execute()
    v_items = v_req.get("items", [])

    video = v_items[0]
    stats = video.get("statistics", {}) # 조회수, 영상 좋아요
    snippet = video.get("snippet", {}) # 영상 정보
    thumbnails = snippet.get("thumbnails", {}) # 썸네일 URL 추출
    thumbnail_url = {k: v["url"] for k, v in thumbnails.items()} # 썸네일 해상도 URL

    video_info.append({
        "video_title": snippet.get("title", "제목 없음"),
        "channel_title": snippet.get("channelTitle", "—"),
        "channel_id": snippet.get("channelId", ""),
        "published_at": time_conversion(snippet.get("publishedAt", "")),
        "view_count": stats.get("viewCount", None),
        "like_count": stats.get("likeCount", None),
        "thumbnail": thumbnail_url
    })

    ch_req = youtube.channels().list( # 채널 아이콘 URL 추출
        part="snippet",
        id=video_info[0]["channel_id"],
    ).execute()
    ch_items = ch_req.get("items", [])

    ch_thumbnails = ch_items[0].get("snippet", {}).get("thumbnails", {})
    ch_thumbnail_url = {k: v["url"] for k, v in ch_thumbnails.items()} # 썸네일 해상도 URL
    video_info[0]["ch_icon_thumbnail"] = ch_thumbnail_url

    return video_info[0]

def fetch_all_comments(video_id: str,
                       api_key: str,
                       max_pages=None,
                       sleep_sec=0.0) -> list[dict]:
    """
    유튜브 댓글 추출
    max_pages가 None일 경우 모든 댓글 추출
    """
    youtube = build(serviceName="youtube", version="v3", developerKey=api_key)

    comments = []
    page_count = 0
    next_token = None

    while True:
        req = youtube.commentThreads().list(
            part="snippet,replies",
            videoId=video_id,
            maxResults=100, # 한 페이지당 100개의 댓글 추출 (기본값 20, 1~100)
            textFormat="plainText",
            pageToken=next_token
        ).execute()

        for item in req.get("items", []):
            comment = item["snippet"]["topLevelComment"]["snippet"] # 댓글 추출
            comments.append({
                "comment_id": item["snippet"]["topLevelComment"]["id"],
                "parent_id": None,
                "author": comment.get("authorDisplayName")[1:],
                "text": comment.get("textDisplay", ""),
                "like_count": comment.get("likeCount", 0),
                # "published_at": comment.get("publishedAt"),
                "updated_at": time_conversion(comment.get("updatedAt")),
                "is_reply": False,
            })
            for replies in item.get("replies", {}).get("comments", []): # 댓글에 달린 대댓글 추출
                reply = replies["snippet"]
                comments.append({
                    "comment_id": replies.get("id"),
                    "parent_id": item["snippet"]["topLevelComment"]["id"],
                    "author": reply.get("authorDisplayName")[1:],
                    "text": reply.get("textDisplay", ""),
                    "like_count": reply.get("likeCount", 0),
                    # "published_at": reply.get("publishedAt"),
                    "updated_at": time_conversion(reply.get("updatedAt")),
                    "is_reply": True,
                })

        page_count += 1
        next_token = req.get("nextPageToken") # 댓글이 많을 경우 다음 페이지의 값 반환 없으면 None

        if max_pages is not None and page_count >= max_pages: # 페이지 수가 정해져있다면 페이지 수까지만
            break
        if not next_token: # 더이상 읽을 페이지가 없다면 break
            break
        if sleep_sec:
            time.sleep(sleep_sec)
    return comments

def basic_tokenize(text: str,
                   min_len=2) -> list[str]:
    """
    한글/영어(소문자)/숫자 외 모든 문자 공백(" ")화
    이모지, 특수기호, 공백(" "), 단일 자음 & 모음(ㅋ,ㅎ 등) 제거
    """
    cleaned = re.sub(r"[^0-9A-Za-z\uAC00-\uD7A3\s]", " ", text)
    tokens = re.split(r"\s+", cleaned.strip().lower())
    return [t for t in tokens if len(t) >= min_len]

# ========== OKT 형태소 분석 ==========
@st.cache_resource(show_spinner=False)
def _get_okt():
    """JDK 설치 후 시스템 환경 변수에 JAVA_HOME 설정 후 재실행"""
    try:
        from konlpy.tag import Okt  # 지연 임포트(미설치 환경 대비)
        return Okt()
    except Exception:
        return None

def okt_tokenize(text: str,
               min_len=2,
               pos_keep=PART_OF_SPEECH,
               stem=True) -> list[str]:
    """
    KONLPY의 OKT
    - norm=True, stem=stem
    - 지정 품사만 남김: 기본값 (명사, 형용사, 동사)
    - 영문은 소문자화
    """
    okt = _get_okt()
    if okt is None:
        return basic_tokenize(text) # JDK 미설치시 실행
    pairs = okt.pos(text, norm=True, stem=stem) # norm: 문장 정규화, stem: 어간 추출
    out = []
    for word, pos in pairs:
        if pos in pos_keep:
            # 한글/영어(소문자화)만 남기고 공백 제거
            cleaned = re.sub(r"[^0-9A-Za-z\uAC00-\uD7A3]", "", word).strip().lower()
            if len(cleaned) >= min_len:
                out.append(cleaned)
    return out

def build_frequency(df: pd.DataFrame,
                    use_ko=True,
                    use_en=True,
                    extra_sw=set(),
                    tokenizer="basic",
                    min_len=2,
                    pos_keep=PART_OF_SPEECH,
                    stem=True) -> Counter:
    """
    텍스트(문장)에 나온 단어마다 갯수를 세아림
    ex) 안녕: 5, 감사: 3 ...
    """
    cnt = Counter()
    for txt in df["text"]:
        if not isinstance(txt, str):
            continue

        if tokenizer == "okt":
            tokens = okt_tokenize(txt, pos_keep=pos_keep, stem=stem)
        else:
            tokens = basic_tokenize(txt, min_len=min_len)

        for t in tokens:
            is_kr = bool(re.search(r"[\uAC00-\uD7A3]", t)) # 가~힣까지 한글일 경우 True
            is_en = bool(re.search(r"[a-z]", t)) # a~z까지 영어일 경우 True

            if is_kr and not use_ko: # 한국어 포함 checkbox False일 경우 필터링
                continue
            if is_en and not use_en: # 영어 포함 checkbox False일 경우 필터링
                continue

            if is_kr and (t in STOPWORDS_KR or t in extra_sw): # 추가적인 한글 불용어 필터
                continue
            if is_en and (t in STOPWORDS_EN or t in extra_sw): # 추가적인 영어 불용어 필터
                continue
            if (not is_kr and not is_en) or (t in extra_sw): # 한글,영어가 아닌 것은 스킵
                continue

            cnt[t] += 1
    return cnt

def make_wordcloud_image(freq_dict: dict,
                         font_path="C:/Windows/Fonts/malgun.ttf",
                         width=1200,
                         height=800):
    """워드 클라우드 생성"""
    if not freq_dict:
        return None
    wc = WordCloud(width=width,
                   height=height,
                   background_color="white",
                   font_path=font_path).generate_from_frequencies(freq_dict)
    img = wc.to_image() # PIL Image로 변환
    return img
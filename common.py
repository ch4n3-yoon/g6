import hashlib
import os
import re
import PIL
import shutil
from fastapi import Request, HTTPException, UploadFile
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from requests import Session
from sqlalchemy import Index, func
from sqlalchemy.orm import load_only
import models
from models import WriteBaseModel
from database import SessionLocal, engine
from datetime import datetime, timedelta, date, time
import json
from PIL import Image
from user_agents import parse


TEMPLATES = "templates"
def get_theme_from_db(config=None):
    # main.py 에서 config 를 인수로 받아서 사용
    if not config:
        db: Session = SessionLocal()
        config = db.query(models.Config).first()
    theme = config.cf_theme if config and config.cf_theme else "basic"
    theme_path = f"{TEMPLATES}/{theme}"
    
    # Check if the directory exists
    if not os.path.exists(theme_path):
        theme_path = f"{TEMPLATES}/basic"
    
    return theme_path

TEMPLATES_DIR = get_theme_from_db()
# print(TEMPLATES_DIR)
ADMIN_TEMPLATES_DIR = "_admin/templates"

SERVER_TIME = datetime.now()
TIME_YMDHIS = SERVER_TIME.strftime("%Y-%m-%d %H:%M:%S")
TIME_YMD = TIME_YMDHIS[:10]

# pc 설정 시 모바일 기기에서도 PC화면 보여짐
# mobile 설정 시 PC에서도 모바일화면 보여짐
# both 설정 시 접속 기기에 따른 화면 보여짐 (pc에서 접속하면 pc화면을, mobile과 tablet에서 접속하면 mobile 화면)
SET_DEVICE = 'both'

# mobile 을 사용하지 않을 경우 False 로 설정
USE_MOBILE = True
    

def hash_password(password: str):
    '''
    비밀번호를 해시화하여 반환하는 함수
    '''
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.hash(password)  


def verify_password(plain_password, hashed_passwd):
    '''
    입력한 비밀번호와 해시화된 비밀번호를 비교하여 일치 여부를 반환하는 함수
    '''
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.verify(plain_password, hashed_passwd)  

# 동적 모델 캐싱: 모델이 이미 생성되었는지 확인하고, 생성되지 않았을 경우에만 새로 생성하는 방법입니다. 
# 이를 위해 간단한 전역 딕셔너리를 사용하여 이미 생성된 모델을 추적할 수 있습니다.
_created_models = {}

# 동적 게시판 모델 생성
def dynamic_create_write_table(table_name: str, create_table: bool = False):
    '''
    WriteBaseModel 로 부터 게시판 테이블 구조를 복사하여 동적 모델로 생성하는 함수
    인수의 table_name 에서는 g6_write_ 를 제외한 테이블 이름만 입력받는다.
    Create Dynamic Write Table Model from WriteBaseModel
    '''
    # 이미 생성된 모델 반환
    if table_name in _created_models:
        return _created_models[table_name]
    
    class_name = "Write" + table_name.capitalize()
    DynamicModel = type(
        class_name, 
        (WriteBaseModel,), 
        {   
            "__tablename__": "g6_write_" + table_name,
            "__table_args__": (
                Index(f'idx_wr_num_reply_{table_name}', 'wr_num', 'wr_reply'),
                Index(f'idex_wr_is_comment_{table_name}', 'wr_is_comment'),
                {"extend_existing": True}),
        }
    )
    # 게시판 추가시 한번만 테이블 생성
    if (create_table):
        DynamicModel.__table__.create(bind=engine, checkfirst=True)
    # 생성된 모델 캐싱
    _created_models[table_name] = DynamicModel
    return DynamicModel

def get_real_client_ip(request: Request):
    '''
    클라이언트의 IP 주소를 반환하는 함수
    '''
    if 'X-Forwarded-For' in request.headers:
        return request.headers.getlist("X-Forwarded-For")[0].split(',')[0]
    return request.remote_addr    


def session_member_key(request: Request, member: models.Member):
    '''
    세션에 저장할 회원의 고유키를 생성하여 반환하는 함수
    '''
    ss_mb_key = hashlib.md5((member.mb_datetime + get_real_client_ip(request) + request.headers.get('User-Agent')).encode()).hexdigest()
    return ss_mb_key


# 회원레벨을 SELECT 형식으로 얻음
def get_member_level_select(id: str, start: int, end: int, selected: int, event=''):
    html_code = []
    html_code.append(f'<select id="{id}" name="{id}" {event}>')
    for i in range(start, end+1):
        html_code.append(f'<option value="{i}" {"selected" if i == selected else ""}>{i}</option>')
    html_code.append('</select>')
    return ''.join(html_code)

    
# skin_gubun(new, search, connect, faq 등) 에 따른 스킨을 SELECT 형식으로 얻음
def get_skin_select(skin_gubun, id, selected, event='', device='pc'):
    skin_path = TEMPLATES_DIR + f"/{skin_gubun}/{device}"
    html_code = []
    html_code.append(f'<select id="{id}" name="{id}" {event}>')
    html_code.append(f'<option value="">선택</option>')
    for skin in os.listdir(skin_path):
        # print(f"{skin_path}/{skin}")
        if os.path.isdir(f"{skin_path}/{skin}"):
            html_code.append(f'<option value="{skin}" {"selected" if skin == selected else ""}>{skin}</option>')
    html_code.append('</select>')
    return ''.join(html_code)


# DHTML 에디터를 SELECT 형식으로 얻음
def get_editor_select(id, selected):
    html_code = []
    html_code.append(f'<select id="{id}" name="{id}">')
    if id == 'bo_select_editor':
        html_code.append(f'<option value="" {"selected" if selected == "" else ""}>기본환경설정의 에디터 사용</option>')
    else:
        html_code.append(f'<option value="">사용안함</option>')
    for editor in os.listdir("static/plugin/editor"):
        if os.path.isdir(f"static/plugin/editor/{editor}"):
            html_code.append(f'<option value="{editor}" {"selected" if editor == selected else ""}>{editor}</option>')
    html_code.append('</select>')
    return ''.join(html_code)


# 회원아이디를 SELECT 형식으로 얻음
def get_member_id_select(id, level, selected, event=''):
    db = SessionLocal()
    # 테이블에서 지정된 필드만 가져 오는 경우 load_only("field1", "field2") 함수를 사용 
    members = db.query(models.Member).options(load_only("mb_id")).filter(models.Member.mb_level >= level).all()
    html_code = []
    html_code.append(f'<select id="{id}" name="{id}" {event}><option value="">선택하세요</option>')
    for member in members:
        html_code.append(f'<option value="{member.mb_id}" {"selected" if member.mb_id == selected else ""}>{member.mb_id}</option>')
    html_code.append('</select>')
    return ''.join(html_code)


# 필드에 저장된 값과 기본 값을 비교하여 selected 를 반환
def get_selected(field_value, value):
    if field_value is None:
        return ''

    if isinstance(value, int):
        return ' selected="selected"' if (int(field_value) == int(value)) else ''
    return ' selected="selected"' if (field_value == value) else ''


def option_array_checked(option, arr=[]):
    checked = ''
    if not isinstance(arr, list):
        arr = arr.split(',')
    if arr and option in arr:
        checked = 'checked="checked"'
    return checked


def get_group_select(id, selected='', event=''):
    db = SessionLocal()
    groups = db.query(models.Group).order_by(models.Group.gr_id).all()
    str = f'<select id="{id}" name="{id}" {event}>\n'
    for i, group in enumerate(groups):
        if i == 0:
            str += '<option value="">선택</option>'
        str += option_selected(group.gr_id, selected, group.gr_subject)
    str += '</select>'
    return str


def option_selected(value, selected, text=''):
    if not text:
        text = value
    if value == selected:
        return f'<option value="{value}" selected="selected">{text}</option>\n'
    else:
        return f'<option value="{value}">{text}</option>\n'
    
    
from urllib.parse import urlencode


def subject_sort_link(request: Request, column: str, query_string: str ='', flag: str ='asc'):
    # 현재 상태에서 sst, sod, sfl, stx, sca, page 값을 가져온다.
    sst = request.state.sst if request.state.sst is not None else ""
    sod = request.state.sod if request.state.sod is not None else ""
    sfl = request.state.sfl if request.state.sfl is not None else ""
    stx = request.state.stx if request.state.stx is not None else ""
    sca = request.state.sca if request.state.sca is not None else ""
    page = request.state.page if request.state.page is not None else "" 
    
    # q1에는 column 값을 추가한다.
    q1 = f"sst={column}"

    if flag == 'asc':
        # flag가 'asc'인 경우, q2에 'sod=asc'를 할당한다.
        q2 = 'sod=asc'
        if sst == column:
            if sod == 'asc':
                # 현재 상태에서 sst와 col이 같고 sod가 'asc'인 경우, q2를 'sod=desc'로 변경한다.
                q2 = 'sod=desc'
    else:
        # flag가 'asc'가 아닌 경우, q2에 'sod=desc'를 할당한다.
        q2 = 'sod=desc'
        if sst == column:
            if sod == 'desc':
                # 현재 상태에서 sst와 col이 같고 sod가 'desc'인 경우, q2를 'sod=asc'로 변경한다.
                q2 = 'sod=asc'

    # query_string, q1, q2를 arr_query 리스트에 추가한다.
    arr_query = []
    arr_query.append(query_string)
    arr_query.append(q1)
    arr_query.append(q2)

    # sfl, stx, sca, page 값이 None이 아닌 경우, 각각의 값을 arr_query에 추가한다.
    if sfl is not None:
        arr_query.append(f'sfl={sfl}')
    if stx is not None:
        arr_query.append(f'stx={stx}')
    if sca is not None:
        arr_query.append(f'sca={sca}')
    if page is not None:
        arr_query.append(f'page={page}')

    # arr_query의 첫 번째 요소를 제외한 나머지 요소를 '&'로 연결하여 qstr에 할당한다.
    qstr = '&'.join(arr_query[1:]) if arr_query else ''
    # qstr을 '&'로 분리하여 pairs 리스트에 저장한다.
    pairs = qstr.split('&')

    # params 딕셔너리를 생성한다.
    params = {}

    # pairs 리스트의 각 요소를 '='로 분리하여 key와 value로 나누고, value가 빈 문자열이 아닌 경우 params에 추가한다.
    for pair in pairs:
        if '=' in pair:
            key, value = pair.split('=')
            if value != '':
                params[key] = value

    # qstr을 쿼리 문자열로 사용하여 링크를 생성하고 반환한다.
    return f'<a href="?{qstr}">'

# 함수 테스트
# print(subject_sort_link('title', query_string='type=list', flag='asc', sst='title', sod='asc', sfl='category', stx='example', page=2))


def get_admin_menus():
    '''
    1, 2단계로 구분된 관리자 메뉴 json 파일이 있으면 load 하여 반환하는 함수
    '''
    files = [
        "_admin/admin_menu_bbs.json",
        "_admin/admin_menu_shop.json",
        "_admin/admin_menu_sms.json"
    ]
    menus = {}
    for file_path in files:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as file:
                menus.update(json.load(file))
    return menus


def get_head_tail_img(dir: str, filename: str):
    '''
    게시판의 head, tail 이미지를 반환하는 함수
    '''
    img_path = os.path.join('data', dir, filename)  # 변수명 변경
    img_exists = os.path.exists(img_path)
    width = None
    
    if img_exists:
        try:
            with Image.open(img_path) as img_file:
                width = img_file.width
                if width > 750:
                    width = 750
        except PIL.UnidentifiedImageError:
            # 이미지를 열 수 없을 때의 처리
            img_exists = False
            print(f"Error: Cannot identify image file '{img_path}'")
    
    return {
        "img_exists": img_exists,
        "img_url": os.path.join('/data', dir, filename) if img_exists else None,
        "width": width
    }
    
def now():
    '''
    현재 시간을 반환하는 함수
    '''
    return datetime.now().timestamp()

import cachetools

# 캐시 크기와 만료 시간 설정
cache = cachetools.TTLCache(maxsize=10000, ttl=3600)

# def generate_one_time_token():
#     '''
#     1회용 토큰을 생성하여 반환하는 함수
#     '''
#     token = os.urandom(24).hex()
#     cache[token] = 'valid'
#     return token


# def validate_one_time_token(token):
#     '''
#     1회용 토큰을 검증하는 함수
#     '''
#     if token in cache:
#         del cache[token]
#         return True
#     return False


def generate_one_time_token(action: str = 'create'):
    '''
    1회용 토큰을 생성하여 반환하는 함수
    action : 'insert', 'update', 'delete' ...
    '''
    token = os.urandom(24).hex()
    cache[token] = {'status': 'valid', 'action': action}
    return token


def validate_one_time_token(token, action: str = 'create'):
    '''
    1회용 토큰을 검증하는 함수
    '''
    token_data = cache.get(token)
    if token_data and token_data.get("action") == action:
        del cache[token]
        return True
    return False


def validate_token_or_raise(token: str = None):
    """토큰을 검증하고 예외를 발생시키는 함수"""
    if not validate_one_time_token(token):
        raise HTTPException(status_code=403, detail="Invalid token.")


def get_client_ip(request: Request):
    '''
    클라이언트의 IP 주소를 반환하는 함수 (PHP의 $_SERVER['REMOTE_ADDR'])
    '''
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # X-Forwarded-For can be a comma-separated list of IPs.
        # The client's requested IP will be the first one.
        client_ip = x_forwarded_for.split(",")[0]
    else:
        client_ip = request.client.host
    return {"client_ip": client_ip}


def make_directory(directory: str):
    """이미지 경로 체크 및 생성

    Args:
        directory (str): 이미지 경로
    """
    if not os.path.exists(directory):
        os.makedirs(directory)


def delete_image(directory: str, filename: str, delete: bool = True):
    """이미지 삭제 처리 함수

    Args:
        directory (str): 경로
        filename (str): 파일이름
        delete (bool): 삭제여부. Defaults to True.
    """
    if delete:
        file_path = f"{directory}{filename}"
        if os.path.exists(file_path):
            os.remove(file_path)


def save_image(directory: str, filename: str, file: UploadFile):
    """이미지 저장 처리 함수

    Args:
        directory (str): 경로
        filename (str): 파일이름
        file (UploadFile): 파일 ojbect
    """
    if file and file.filename:
        with open(f"{directory}{filename}", "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            

def outlogin(request: Request):
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    member = request.state.context["member"]
    if member:
        temp = templates.TemplateResponse("bbs/outlogin_after.html", {"request": request, "member": member})
    else:
        temp = templates.TemplateResponse("bbs/outlogin_before.html", {"request": request, "member": None})
    return temp.body.decode("utf-8")


def generate_query_string(request: Request):
    search_fields = {}
    if request.method == "GET":
        search_fields = {
            'sst': request.query_params.get("sst"),
            'sod': request.query_params.get("sod"),
            'sfl': request.query_params.get("sfl"),
            'stx': request.query_params.get("stx"),
            'sca': request.query_params.get("sca"),
            # 'page': request.query_params.get("page")
        }
    else:
        search_fields = {
            'sst': request._form.get("sst") if request._form else "",
            'sod': request._form.get("sod") if request._form else "",
            'sfl': request._form.get("sfl") if request._form else "",
            'stx': request._form.get("stx") if request._form else "",
            'sca': request._form.get("sca") if request._form else "",
            # 'page': request._form.get("page") if request._form else ""
        }    
        
    # None 값을 제거
    search_fields = {k: v for k, v in search_fields.items() if v is not None}

    return urlencode(search_fields)    

        
# 파이썬의 내장함수인 list 와 이름이 충돌하지 않도록 변수명을 lst 로 변경함
def get_from_list(lst, index, default=0):
    if lst is None:
        return default
    try:
        return 1 if index in lst else default
    except (TypeError, IndexError):
        return default


# 그누보드5 get_paging() 함수와 다른점
# 1. 인수에서 write_pages 삭제
# 2. 인수에서 total_page 대신 total_records 를 사용함

# current_page : 현재 페이지
# total_records : 전체 레코드 수
# url_prefix : 페이지 링크의 URL 접두사
# add_url : 페이지 링크의 추가 URL
def get_paging(request, current_page, total_records, url_prefix, add_url=""):
    
    config = request.state.config
    try:
        current_page = int(current_page)
    except ValueError:
        # current_page가 정수로 변환할 수 없는 경우 기본값으로 1을 사용하도록 설정
        current_page = 1
    total_records = int(total_records)

    # 한 페이지당 라인수
    page_rows = config.cf_mobile_page_rows if request.state.is_mobile and config.cf_mobile_page_rows else config.cf_page_rows
    # 페이지 표시수
    page_count = config.cf_mobile_pages if request.state.is_mobile and config.cf_mobile_pages else config.cf_write_pages
    
    # 올바른 total_pages 계산 (올림처리)
    total_pages = (total_records + page_rows - 1) // page_rows
    
    # print(page_rows, page_count, total_pages)
    
    # 페이지 링크 목록 초기화
    page_links = []
    
    start_page = ((current_page - 1) // page_count) * page_count + 1
    end_page = start_page + page_count - 1

    # # 중앙 페이지 계산
    middle = page_count // 2
    start_page = max(1, current_page - middle)
    end_page = min(total_pages, start_page + page_count - 1)
    
    # 처음 페이지 링크 생성
    if current_page > 1:
        start_url = f"{url_prefix}1{add_url}"
        page_links.append(f'<a href="{start_url}" class="pg_page pg_start" title="처음 페이지">처음</a>')

    # 이전 페이지 구간 링크 생성
    if start_page > 1:
        prev_page = max(current_page - page_count, 1) 
        prev_url = f"{url_prefix}{prev_page}{add_url}"
        page_links.append(f'<a href="{prev_url}" class="pg_page pg_prev" title="이전 구간">이전</a>')

    # 페이지 링크 생성
    for page in range(start_page, end_page + 1):
        page_url = f"{url_prefix}{page}{add_url}"
        if page == current_page:
            page_links.append(f'<a href="{page_url}"><strong class="pg_current" title="현재 {page} 페이지">{page}</strong></a>')
        else:
            page_links.append(f'<a href="{page_url}" class="pg_page" title="{page} 페이지">{page}</a>')

    # 다음 페이지 구간 링크 생성
    if total_pages > end_page:
        next_page = min(current_page + page_count, total_pages)
        next_url = f"{url_prefix}{next_page}{add_url}"
        page_links.append(f'<a href="{next_url}" class="pg_page pg_next" title="다음 구간">다음</a>')
    
    # 마지막 페이지 링크 생성        
    if current_page < total_pages:
        end_url = f"{url_prefix}{total_pages}{add_url}"
        page_links.append(f'<a href="{end_url}" class="pg_page pg_end" title="마지막 페이지">마지막</a>')

    # 페이지 링크 목록을 문자열로 변환하여 반환
    return '<nav class="pg_wrap"><span class="pg">' + ''.join(page_links) + '</span></nav>'


def extract_browser(user_agent):
    # 사용자 에이전트 문자열에서 브라우저 정보 추출
    # 여기에 필요한 정규 표현식 또는 분석 로직을 추가
    # 예를 들어, 단순히 "Mozilla/5.0" 문자열을 추출하는 예제
    browser_match = re.search(r"Mozilla/5.0", user_agent)
    if browser_match:
        return "Mozilla/5.0"
    else:
        return "Unknown"
    
from ua_parser import user_agent_parser    
    

# 접속 레코드 기록 로직을 처리하는 함수
def record_visit(request: Request):
    vi_ip = request.client.host
    
    Visit = models.Visit
    VisitSum = models.VisitSum

    # 세션 생성
    db = SessionLocal()

    # 오늘의 접속이 이미 기록되어 있는지 확인
    existing_visit = db.query(Visit).filter(Visit.vi_date == date.today(), Visit.vi_ip == vi_ip).first()

    if not existing_visit:
        # 새로운 접속 레코드 생성
        referer = request.headers.get("referer", "")
        user_agent = request.headers.get("User-Agent", "")
        ua = parse(user_agent)
        browser = ua.browser.family
        os = ua.os.family
        device = 'pc' if ua.is_pc else 'mobile' if ua.is_mobile else 'tablet' if ua.is_tablet else 'unknown'
            
        visit = Visit(
            vi_ip=vi_ip,
            vi_date=date.today(),
            vi_time=datetime.now().time(),
            vi_referer=referer,
            vi_agent=user_agent,
            vi_browser=browser,
            vi_os=os,
            vi_device=device,   
        )
        db.add(visit)
        db.commit()

        # VisitSum 테이블 업데이트
        visit_count_today = db.query(func.count(Visit.vi_id)).filter(Visit.vi_date == date.today()).scalar()

        visit_sum = db.query(VisitSum).filter(VisitSum.vs_date == date.today()).first()
        if visit_sum:
            visit_sum.vs_count = visit_count_today
        else:
            visit_sum = VisitSum(vs_date=date.today(), vs_count=visit_count_today)

        db.add(visit_sum)
        db.commit()

    db.close()            
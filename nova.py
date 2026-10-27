# -*- coding: utf-8 -*-
"""
Nova Messenger v10 — мессенджер для Pydroid 3
Запуск: pip install flask -> Run. Ссылка для друзей напечатается в консоли.
Один файл. База: nova4.db (старые аккаунты СОХРАНЯЮТСЯ, база обновляется сама).

Новое в v10:
 • Сервер открыт для других: http://<IP-телефона>:5000 (одна Wi-Fi сеть) или публичная ссылка через ngrok
 • Системные номера без кода: +8880001488, +999, +777 (занятые не показываются)
 • Вход по номеру: код приходит сообщением в твой аккаунт (чат Nova Support)
 • Убраны боты-фармилки. Звёзды: ежедневный бонус и NFT-рулетка; очки ранга — от NFT
 • Новые NFT (красивые карточки с голограммной рамкой), 12 рангов
 • Апелляции: пользователь пишет объяснение в @SpamBot_Info, затем /appeal — апелляция уходит
   человеку-модератору через @novasupport (укажи свой ник в ADMINS), ответ приходит обратно
 • Как в Telegram: поиск по чату, закреп сообщений, архив чатов, очистка истории
 • Исправлен /help у Nova Support
"""
import base64, hashlib, hmac, json, os, re, secrets, smtplib, socket, sqlite3, struct, threading, time
import urllib.request, webbrowser
from contextlib import closing
from email.message import EmailMessage
from functools import wraps
from flask import Flask, jsonify, request, session, Response, g as G
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash as gph, check_password_hash as cph

# ───────── НАСТРОЙКИ ─────────
HOST, PORT = "0.0.0.0", int(os.environ.get("PORT", 5000))  # 0.0.0.0 = зайти могут и другие устройства по ссылке
NGROK_TOKEN = ""  # (необязательно) токен с ngrok.com + pip install pyngrok -> публичная ссылка для всего интернета
ADMINS = []  # ники людей-модераторов, получают апелляции, напр. ["MyNick"]; пусто = апелляции проверяются автоматически
SMS_CODE = "12345"  # код подтверждения при РЕГИСТРАЦИИ обычного номера
COUNTRIES = [("7", "🇷🇺", "Россия / Казахстан"), ("380", "🇺🇦", "Украина"), ("375", "🇧🇾", "Беларусь"),
             ("998", "🇺🇿", "Узбекистан"), ("996", "🇰🇬", "Киргизия"), ("995", "🇬🇪", "Грузия"),
             ("374", "🇦🇲", "Армения"), ("994", "🇦🇿", "Азербайджан"), ("1", "🇺🇸", "США / Канада"),
             ("44", "🇬🇧", "Великобритания"), ("49", "🇩🇪", "Германия"), ("33", "🇫🇷", "Франция"),
             ("39", "🇮🇹", "Италия"), ("34", "🇪🇸", "Испания"), ("48", "🇵🇱", "Польша"), ("90", "🇹🇷", "Турция"),
             ("971", "🇦🇪", "ОАЭ"), ("91", "🇮🇳", "Индия"), ("86", "🇨🇳", "Китай"), ("81", "🇯🇵", "Япония"),
             ("82", "🇰🇷", "Корея"), ("55", "🇧🇷", "Бразилия")]
SYSNUMS = ["+8880001488", "+999", "+777"]  # системные номера: без кода, один аккаунт на номер
PHONES = {p: None for p in SYSNUMS}
PHONE_GROUPS = []
for _cc, _fl, _nm in COUNTRIES:  # у каждой страны 5 номеров вида +<код>5550001 ... +<код>5550005
    _L = ["+%s55500%02d" % (_cc, _i) for _i in range(1, 6)]
    for _p in _L:
        PHONES[_p] = SMS_CODE
    PHONE_GROUPS.append((_fl, _nm, _L))
GOOGLE_CLIENT_ID = ""
SMTP = {"host": "smtp.gmail.com", "port": 465, "user": "", "pass": ""}
RESERVED = {"admin", "administrator", "support", "nova", "novagram", "root", "system", "telegram", "moderator",
            "ratra", "spambot", "reyt"}
APPEAL_SEC = 90  # автопроверка апелляции (только если ADMINS пуст)
DEL_DAYS = 7
IMG_RE = r"^data:image/(jpeg|png|webp|gif);base64,[A-Za-z0-9+/=]+$"
FROZEN_NAME = "Удалённый аккаунт"

BASE = os.path.dirname(os.path.abspath(__file__))
for _s in ("", "-wal", "-shm", ".key"):  # совсем старая база v5
    try:
        os.remove(os.path.join(BASE, "nova3.db" + _s))
    except OSError:
        pass
DB = os.path.join(BASE, "nova4.db")
KEYF = DB + ".key"
if not os.path.exists(KEYF):
    with open(KEYF, "w") as _f:
        _f.write(secrets.token_hex(32))
app = Flask(__name__)
with open(KEYF) as _f:
    app.secret_key = _f.read().strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=86400 * 60,
                  MAX_CONTENT_LENGTH=6 * 1024 * 1024)

GIFTS = [{"id": "rose", "e": "🌹", "n": "Роза", "p": 10}, {"id": "bear", "e": "🧸", "n": "Мишка", "p": 25},
         {"id": "cake", "e": "🎂", "n": "Торт", "p": 40}, {"id": "rocket", "e": "🚀", "n": "Ракета", "p": 60},
         {"id": "diamond", "e": "💎", "n": "Бриллиант", "p": 100}, {"id": "crown", "e": "👑", "n": "Корона", "p": 150}]
GMAP = {x["id"]: x for x in GIFTS}
NFTS = [{"id": "orb", "n": "Магический шар", "r": "Редкий", "w": 30, "c": ["#9b86ff", "#ff5cf0"]},
        {"id": "butterfly", "n": "Неоновая бабочка", "r": "Редкий", "w": 30, "c": ["#19e0ff", "#6a7dff"]},
        {"id": "lotus", "n": "Лотос", "r": "Редкий", "w": 25, "c": ["#ff9acb", "#ff4d8d"]},
        {"id": "crystal", "n": "Кристалл", "r": "Эпический", "w": 12, "c": ["#6be8ff", "#8a3cff"]},
        {"id": "planet", "n": "Космос", "r": "Эпический", "w": 10, "c": ["#7be0ff", "#a855f7"]},
        {"id": "moon", "n": "Лунный серп", "r": "Эпический", "w": 9, "c": ["#a9bcff", "#5a3cd0"]},
        {"id": "star", "n": "Звезда", "r": "Легендарный", "w": 5, "c": ["#ffe066", "#ff9a00"]},
        {"id": "crown", "n": "Корона", "r": "Легендарный", "w": 4, "c": ["#ffd84a", "#ff8f00"]},
        {"id": "diamond", "n": "Алмаз", "r": "Легендарный", "w": 3, "c": ["#b9f6ff", "#3aa0ff"]},
        {"id": "phoenix", "n": "Феникс", "r": "Мифический", "w": 2, "c": ["#ff6a3a", "#ffc400"]}]
NMAP = {x["id"]: x for x in NFTS}
RP = {"Редкий": 40, "Эпический": 100, "Легендарный": 250, "Мифический": 500}
ANIMS = [["float", "Парение"], ["spin", "Вращение"], ["pulse", "Пульс"], ["glow", "Сияние"],
         ["swing", "Маятник"], ["rainbow", "Радуга"]]
AMAP = {a[0] for a in ANIMS}
STICKERS = ["😀", "😂", "😍", "😎", "😭", "😡", "🥳", "🤔", "👍", "👎", "🙏", "🔥", "❤️", "💔", "🎉", "🐱",
            "🐶", "🦊", "🐼", "🍕", "⚽", "🚀", "🌈", "💩"]
REACTS = ["👍", "❤️", "😂", "😮", "😢", "🔥"]
SPIN_PRICE, NFT_NAME_PRICE, NFT_NAME_PTS = 100, 50, 150
LV = [0, 100, 300, 700, 1500, 3000, 6000, 12000, 25000, 50000, 100000, 200000]  # пороги 12 рангов
RANKN = ["Новичок", "Участник", "Активный", "Мастер", "Эксперт", "Легенда", "Титан", "Бессмертный",
         "Властелин", "Архонт", "Небожитель", "Абсолют"]
PREM = {"month": (50, 30), "year": (100, 365)}

# ───────── БАЗА ДАННЫХ ─────────
SCHEMA = """
CREATE TABLE users(
 id INTEGER PRIMARY KEY AUTOINCREMENT, nick TEXT NOT NULL UNIQUE COLLATE NOCASE, pw TEXT NOT NULL,
 name TEXT NOT NULL DEFAULT '', bio TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
 email TEXT NOT NULL DEFAULT '', email_ok INTEGER NOT NULL DEFAULT 0,
 avatar TEXT NOT NULL DEFAULT '', avts INTEGER NOT NULL DEFAULT 0,
 stars INTEGER NOT NULL DEFAULT 100 CHECK(stars>=0), score INTEGER NOT NULL DEFAULT 0,
 prem_until REAL NOT NULL DEFAULT 0, bonus_ts REAL NOT NULL DEFAULT 0,
 totp TEXT, totp_on INTEGER NOT NULL DEFAULT 0, akey TEXT, gsub TEXT UNIQUE,
 is_bot INTEGER NOT NULL DEFAULT 0, owner INTEGER REFERENCES users(id) ON DELETE CASCADE,
 nft_eq INTEGER NOT NULL DEFAULT 0, nft_bg INTEGER NOT NULL DEFAULT 0, verified INTEGER NOT NULL DEFAULT 0,
 seen REAL NOT NULL DEFAULT 0, created REAL NOT NULL DEFAULT 0, nu_show TEXT NOT NULL DEFAULT '',
 frozen INTEGER NOT NULL DEFAULT 0, blk_by INTEGER NOT NULL DEFAULT 0,
 frz_ts REAL NOT NULL DEFAULT 0, frz_why TEXT NOT NULL DEFAULT '', appeal_ts REAL NOT NULL DEFAULT 0,
 appeals INTEGER NOT NULL DEFAULT 0, del_at REAL NOT NULL DEFAULT 0, bday TEXT NOT NULL DEFAULT '',
 hide_seen INTEGER NOT NULL DEFAULT 0, appeal_txt TEXT NOT NULL DEFAULT '');
CREATE UNIQUE INDEX ix_users_phone ON users(phone) WHERE phone!='';
CREATE INDEX ix_users_email ON users(email);
CREATE TABLE sess(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 tok TEXT NOT NULL UNIQUE, ip TEXT DEFAULT '', device TEXT DEFAULT '', country TEXT DEFAULT '', city TEXT DEFAULT '',
 created REAL, seen REAL);
CREATE INDEX ix_sess_uid ON sess(uid);
CREATE TABLE codes(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 kind TEXT NOT NULL, dest TEXT, hash TEXT NOT NULL, exp REAL NOT NULL, tries INTEGER NOT NULL DEFAULT 0, ts REAL NOT NULL);
CREATE TABLE grps(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN('group','channel')),
 title TEXT NOT NULL, owner INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 uname TEXT COLLATE NOCASE, bio TEXT NOT NULL DEFAULT '', nft INTEGER NOT NULL DEFAULT 0,
 frozen INTEGER NOT NULL DEFAULT 0, blk_by INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX ix_grps_un ON grps(uname) WHERE uname IS NOT NULL;
CREATE TABLE members(g INTEGER REFERENCES grps(id) ON DELETE CASCADE, uid INTEGER REFERENCES users(id) ON DELETE CASCADE,
 admin INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(g,uid));
CREATE INDEX ix_mem_uid ON members(uid);
CREATE TABLE msgs(id INTEGER PRIMARY KEY AUTOINCREMENT, frm INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 uid INTEGER REFERENCES users(id) ON DELETE CASCADE, gid INTEGER REFERENCES grps(id) ON DELETE CASCADE,
 text TEXT NOT NULL DEFAULT '', gift TEXT, sticker TEXT, rep INTEGER, edt REAL NOT NULL DEFAULT 0,
 ts REAL NOT NULL, img TEXT NOT NULL DEFAULT '', fwd TEXT NOT NULL DEFAULT '', CHECK((uid IS NULL)!=(gid IS NULL)));
CREATE INDEX ix_msgs_uid ON msgs(uid,id);
CREATE INDEX ix_msgs_gid ON msgs(gid,id);
CREATE INDEX ix_msgs_frm ON msgs(frm,id);
CREATE TABLE rdst(uid INTEGER NOT NULL, peer INTEGER NOT NULL, lid INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(uid,peer));
CREATE TABLE unames(name TEXT PRIMARY KEY COLLATE NOCASE, uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 nft INTEGER NOT NULL DEFAULT 0);
CREATE TABLE bcmd(id INTEGER PRIMARY KEY AUTOINCREMENT, bot INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 trig TEXT NOT NULL, reply TEXT NOT NULL);
CREATE TABLE bstate(uid INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE nftg(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 kind TEXT NOT NULL, anim TEXT NOT NULL DEFAULT 'float', ts REAL NOT NULL);
CREATE INDEX ix_nftg_uid ON nftg(uid);
CREATE TABLE tx(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 amount INTEGER NOT NULL, why TEXT, ts REAL NOT NULL);
CREATE INDEX ix_tx_uid ON tx(uid);
CREATE TABLE follows(a INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 b INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, ts REAL, PRIMARY KEY(a,b));
CREATE INDEX ix_fol_b ON follows(b);
CREATE TABLE react(mid INTEGER NOT NULL REFERENCES msgs(id) ON DELETE CASCADE,
 uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, e TEXT NOT NULL, ts REAL NOT NULL, PRIMARY KEY(mid,uid));
CREATE TABLE pins(uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, peer INTEGER NOT NULL, PRIMARY KEY(uid,peer));
CREATE TABLE mutes(uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, peer INTEGER NOT NULL, PRIMARY KEY(uid,peer));
CREATE TABLE blocks(a INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 b INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, PRIMARY KEY(a,b));
CREATE TABLE tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 text TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE clr(uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, peer INTEGER NOT NULL,
 lid INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(uid,peer));
CREATE TABLE arch(uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, peer INTEGER NOT NULL, PRIMARY KEY(uid,peer));
CREATE TABLE pmsg(k TEXT PRIMARY KEY, mid INTEGER NOT NULL REFERENCES msgs(id) ON DELETE CASCADE);
"""
# обновление старой базы (-> v4), каждая команда безопасна
MIGR = [
    "ALTER TABLE users ADD COLUMN nu_show TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE grps ADD COLUMN uname TEXT COLLATE NOCASE",
    "ALTER TABLE grps ADD COLUMN bio TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE grps ADD COLUMN nft INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE members ADD COLUMN admin INTEGER NOT NULL DEFAULT 0",
    "CREATE TABLE IF NOT EXISTS react(mid INTEGER NOT NULL REFERENCES msgs(id) ON DELETE CASCADE, "
    "uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, e TEXT NOT NULL, ts REAL NOT NULL, PRIMARY KEY(mid,uid))",
    "CREATE TABLE IF NOT EXISTS pins(uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
    "peer INTEGER NOT NULL, PRIMARY KEY(uid,peer))",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_grps_un ON grps(uname) WHERE uname IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_phone_u ON users(phone) WHERE phone!=''",
    "UPDATE users SET nick='novasupport' WHERE nick='Nova Support'",
    "ALTER TABLE users ADD COLUMN frozen INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN blk_by INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE grps ADD COLUMN frozen INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE grps ADD COLUMN blk_by INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE msgs ADD COLUMN img TEXT NOT NULL DEFAULT ''",
]
MIGR5 = [
    "ALTER TABLE users ADD COLUMN frz_ts REAL NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN frz_why TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE users ADD COLUMN appeal_ts REAL NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN appeals INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN del_at REAL NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN bday TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE users ADD COLUMN hide_seen INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE msgs ADD COLUMN fwd TEXT NOT NULL DEFAULT ''",
    "CREATE TABLE IF NOT EXISTS mutes(uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
    "peer INTEGER NOT NULL, PRIMARY KEY(uid,peer))",
    "CREATE TABLE IF NOT EXISTS blocks(a INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
    "b INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, PRIMARY KEY(a,b))",
    "CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, text TEXT NOT NULL, ts REAL NOT NULL)",
]
MIGR6 = [
    "ALTER TABLE users ADD COLUMN appeal_txt TEXT NOT NULL DEFAULT ''",
    "CREATE TABLE IF NOT EXISTS clr(uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
    "peer INTEGER NOT NULL, lid INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(uid,peer))",
    "CREATE TABLE IF NOT EXISTS arch(uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
    "peer INTEGER NOT NULL, PRIMARY KEY(uid,peer))",
    "CREATE TABLE IF NOT EXISTS pmsg(k TEXT PRIMARY KEY, mid INTEGER NOT NULL REFERENCES msgs(id) ON DELETE CASCADE)",
]
BOTS = (("novasupport", "Nova Support", "Служба поддержки Nova. Сюда приходят коды и уведомления."),
        ("Nova_NFT_bot", "Nova NFT", "Превращай юзернеймы в NFT 💎"),
        ("Galochka_bot", "Galochka", "Выдаю галочку «Проверено NovaGram» ✅"),
        ("Ratra_bot", "Ratra", "Модератор NovaGram 🐀 Блокирую нарушителей: пришли мне @юзернейм ❄️"),
        ("SpamBot_Info", "Spam Bot Info", "Заморозка и разморозка аккаунтов NovaGram 🛡"))
OLD_BOTS = ("Stars_bot", "Reyt_bot")  # убраны в v10
BOTCMDS = {"Galochka_bot": ["/start", "/get", "/remove"], "Nova_NFT_bot": ["/start"],
           "Ratra_bot": ["/start", "/block", "/unblock", "/list", "/stats"],
           "SpamBot_Info": ["/start", "/status", "/appeal", "/rules"],
           "novasupport": ["/start", "/help", "/password", "/nft", "/ranks", "/verify", "/email", "/features",
                           "/tickets", "/delete"]}
BC = {k.lower(): v for k, v in BOTCMDS.items()}


def now():
    return time.time()


def db():
    con = sqlite3.connect(DB, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.create_function("ulow", 1, lambda s: (s or "").casefold())
    return con


def q(sql, a=(), one=False, w=False):
    with closing(db()) as con:
        cur = con.execute(sql, a)
        rows = cur.fetchall()
        if w:
            con.commit()
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount
    return (rows[0] if rows else None) if one else rows


def init_db():
    with closing(db()) as con:
        v = con.execute("PRAGMA user_version").fetchone()[0]
        has = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        if v == 0 and not has:
            con.executescript(SCHEMA)
        else:
            for ver, lst in ((4, MIGR), (5, MIGR5), (6, MIGR6)):
                if v < ver:
                    for s in lst:
                        try:
                            con.execute(s)
                        except sqlite3.Error:
                            pass
        con.execute("PRAGMA user_version=6")
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        con.commit()
    try:  # приводим ник поддержки к одному виду (@novasupport) и убираем старых ботов-фармилок
        q("UPDATE users SET nick='novasupport' WHERE is_bot=1 AND owner IS NULL AND lower(replace(nick,' ',''))='novasupport'", w=True)
    except sqlite3.Error:
        pass
    for n in OLD_BOTS:
        q("DELETE FROM users WHERE nick=? AND is_bot=1 AND owner IS NULL", (n,), w=True)
    for nick, name, bio in BOTS:
        if not q("SELECT 1 FROM users WHERE nick=?", (nick,), one=True):
            q("INSERT INTO users(nick,pw,name,bio,is_bot,verified,created) VALUES(?,?,?,?,1,1,?)",
              (nick, gph(secrets.token_hex(16)), name, bio, now()), w=True)


# ───────── БЕЗОПАСНОСТЬ ─────────
def h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def hc(s):
    return hmac.new(app.secret_key.encode(), s.encode(), hashlib.sha256).hexdigest()


_T = {}


def hot(key, n=8, win=300):
    t = now()
    L = [x for x in _T.get(key, []) if t - x < win] + [t]
    _T[key] = L
    return len(L) > n


def locked(key, n=8, win=300):  # считаем только НЕУДАЧНЫЕ попытки
    t = now()
    return sum(1 for x in _T.get(key, []) if t - x < win) >= n


def bad(key):
    _T.setdefault(key, []).append(now())


def ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()


def totp(secret, t=None):
    c = int((t or time.time()) // 30)
    d = hmac.new(base64.b32decode(secret), struct.pack(">Q", c), hashlib.sha1).digest()
    o = d[-1] & 15
    return "%06d" % ((struct.unpack(">I", d[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6)


def totp_ok(secret, code):
    return bool(secret) and any(hmac.compare_digest(totp(secret, time.time() + k * 30), str(code).strip())
                                for k in (-1, 0, 1))


def dev(ua):
    m = re.search(r"Android [\d.]+; ([^;)]+)", ua)
    o = ("Android" if not m or m[1].strip() == "K" else m[1].strip()) if "Android" in ua else next(
        (n for k, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"), ("Mac OS", "Mac"),
                        ("Linux", "Linux")) if k in ua), "Устройство")
    b = next((n for k, n in (("Edg", "Edge"), ("OPR", "Opera"), ("YaBrowser", "Яндекс Браузер"), ("Firefox", "Firefox"),
                             ("SamsungBrowser", "Samsung Internet"), ("CriOS", "Chrome"), ("Chrome", "Chrome"),
                             ("Safari", "Safari")) if k in ua), "Браузер")
    return o + " · " + b


_G = {}


def geo(addr):
    k = "" if re.match(r"^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1|fe80|f[cd])", addr or "127.") else addr
    if k in _G and now() - _G[k][0] < 1800:
        return _G[k][1]
    for url in ("https://ipwho.is/%s?lang=ru" % k,
                "http://ip-api.com/json/%s?fields=status,country,city,query&lang=ru" % k):
        try:
            d = json.loads(urllib.request.urlopen(url, timeout=6).read())
            if d.get("success") is False or d.get("status") == "fail":
                continue
            r = (d.get("country") or "", d.get("city") or "", d.get("ip") or d.get("query") or addr)
            _G[k] = (now(), r)
            return r
        except Exception:
            continue
    return "", "", addr


def new_sess(uid):
    """Создаёт сессию. Если аккаунт был в «отложенном удалении» — возвращает его (возвращает True)."""
    restored = False
    if q("UPDATE users SET frozen=0, del_at=0 WHERE id=? AND frozen=2", (uid,), w=True):
        restored = True
        notify(uid, "🎉 С возвращением! Удаление аккаунта отменено — сообщения, NFT, звёзды и юзернеймы на месте.")
    session.clear()
    t, a = secrets.token_urlsafe(32), ip()
    sid = q("INSERT INTO sess(uid,tok,ip,device,created,seen) VALUES(?,?,?,?,?,?)",
            (uid, h(t), a, dev(request.headers.get("User-Agent", "")), now(), now()), w=True)
    session.permanent = True
    session["t"] = t

    def look():
        try:
            c, ci, real = geo(a)
            q("UPDATE sess SET country=?, city=?, ip=? WHERE id=?", (c, ci, real or a, sid), w=True)
        except Exception:
            pass
    threading.Thread(target=look, daemon=True).start()
    return restored


def me():
    t = session.get("t")
    s = q("SELECT * FROM sess WHERE tok=?", (h(t),), one=True) if t else None
    if not s:
        return None
    G.sid, n = s["id"], now()
    if n - s["seen"] > 20:
        q("UPDATE sess SET seen=? WHERE id=?", (n, s["id"]), w=True)
        q("UPDATE users SET seen=? WHERE id=?", (n, s["uid"]), w=True)
    return q("SELECT * FROM users WHERE id=?", (s["uid"],), one=True)


# замороженный аккаунт может только читать, выходить и писать в @SpamBot_Info
FROZEN_OK = {"/api/logout", "/api/send", "/api/devices/info"}


def need_login(f):
    @wraps(f)
    def w(*a, **k):
        u = me()
        if not u:
            return jsonify(error="Нужно войти"), 401
        if u["frozen"] == 1 and request.method == "POST" and request.path not in FROZEN_OK:
            return jsonify(error="❄️ Аккаунт заморожен. Напиши в @SpamBot_Info"), 403
        return f(*a, **k)
    return w


def err(m, c=400):
    return jsonify(error=m), c


@app.errorhandler(Exception)
def oops(e):  # любая ошибка сервера -> понятный JSON, а не пустой ответ
    if isinstance(e, HTTPException):
        if e.code == 413:
            return err("Файл слишком большой", 413)
        return e
    if isinstance(e, sqlite3.IntegrityError):
        return err("Это значение уже занято")
    return err("Ошибка сервера: %s" % e.__class__.__name__, 500)


# ───────── ЗВЁЗДЫ, РАНГИ, КОДЫ, ПОЧТА ─────────
def lvl(score):
    return sum(score >= t for t in LV)


def spend(uid, n, why):
    if q("UPDATE users SET stars=stars-? WHERE id=? AND stars>=? AND frozen=0", (n, uid, n), w=True):
        q("INSERT INTO tx(uid,amount,why,ts) VALUES(?,?,?,?)", (uid, -n, why, now()), w=True)
        return True
    return False


def add_score(uid, p):
    a = q("SELECT score FROM users WHERE id=?", (uid,), one=True)["score"]
    q("UPDATE users SET score=score+? WHERE id=?", (p, uid), w=True)
    if lvl(a + p) > lvl(a):
        notify(uid, "🎉 Поздравляем! Твой ранг повышен: %d — %s." % (lvl(a + p), RANKN[lvl(a + p) - 1]))
    return lvl(a), lvl(a + p)


def say(frm, uid, text):
    q("INSERT INTO msgs(frm,uid,text,ts) VALUES(?,?,?,?)", (frm, uid, text, now()), w=True)


def bot_id(nick):
    r = q("SELECT id FROM users WHERE nick=?", (nick,), one=True)
    return r["id"] if r else 0


def notify(uid, text):
    r = q("SELECT id FROM users WHERE nick='novasupport'", one=True)
    if r:
        say(r["id"], uid, text)


def admin_ids():
    out = []
    for n in ADMINS:
        r = q("SELECT id FROM users WHERE nick=? AND is_bot=0 AND frozen=0", (str(n).lstrip("@"),), one=True)
        if r:
            out.append(r["id"])
    return out


def mail(to, subj, body):
    if not (SMTP["user"] and SMTP["pass"]):
        return "Почта сервера не настроена: впиши SMTP user/pass в начале файла"
    try:
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = "Nova <%s>" % SMTP["user"], to, subj
        m.set_content(body)
        with smtplib.SMTP_SSL(SMTP["host"], SMTP["port"], timeout=15) as s:
            s.login(SMTP["user"], SMTP["pass"])
            s.send_message(m)
    except Exception as e:
        return "Не удалось отправить письмо (%s)" % e.__class__.__name__


def mask(e):
    a, b = e.split("@")
    return a[0] + "***@" + b


def send_code(u, kind, dest, title):
    r = q("SELECT ts FROM codes WHERE uid=? AND kind=?", (u["id"], kind), one=True)
    if r and now() - r["ts"] < 60:
        return "Подожди минуту перед повторной отправкой"
    c = "%06d" % secrets.randbelow(10 ** 6)
    q("DELETE FROM codes WHERE uid=? AND kind=?", (u["id"], kind), w=True)
    q("INSERT INTO codes(uid,kind,dest,hash,exp,ts) VALUES(?,?,?,?,?,?)",
      (u["id"], kind, dest, hc(c), now() + 600, now()), w=True)
    e = mail(dest, "Nova — " + title, "Ваш код: %s\nДействует 10 минут.\nЕсли это были не вы — игнорируйте письмо." % c)
    if e:
        q("DELETE FROM codes WHERE uid=? AND kind=?", (u["id"], kind), w=True)
        return e
    notify(u["id"], "🔐 %s\nКод: %s\nОтправлен на почту: %s\nДействует 10 минут." % (title, c, mask(dest)))


def check_code(uid, kind, code):
    r = q("SELECT * FROM codes WHERE uid=? AND kind=?", (uid, kind), one=True)
    if not r or r["exp"] < now() or r["tries"] >= 5:
        return None
    q("UPDATE codes SET tries=tries+1 WHERE id=?", (r["id"],), w=True)
    if not hmac.compare_digest(r["hash"], hc(str(code).strip())):
        return None
    q("DELETE FROM codes WHERE id=?", (r["id"],), w=True)
    return r


# ───────── ПУБЛИЧНЫЕ ДАННЫЕ ─────────
def nft_of(u, col="nft_eq"):
    i = u[col]
    e = q("SELECT * FROM nftg WHERE id=? AND uid=?", (i, u["id"]), one=True) if i else None
    return {"id": e["id"], "kind": e["kind"], "anim": e["anim"]} if e else None


def nu_of(u):  # NFT-юзернейм, который пользователь выбрал показывать в профиле
    n = u["nu_show"]
    if n and q("SELECT 1 FROM unames WHERE name=? AND uid=? AND nft=1", (n, u["id"]), one=True):
        return n
    return None


def pub(u, real=False):
    fz = u["frozen"]
    if fz and not real:  # замороженный/удаляемый аккаунт для остальных выглядит как «Удалённый аккаунт»
        return {"id": u["id"], "nick": "deleted", "name": FROZEN_NAME, "bio": "", "bot": bool(u["is_bot"]),
                "nft": None, "prem": False, "lvl": 0, "ver": False, "seen": 0, "nu": None, "av": None,
                "frozen": fz == 1, "gone": True, "hs": False}
    hs = bool(u["hide_seen"]) and not real
    return {"id": u["id"], "nick": u["nick"], "name": u["name"] or u["nick"], "bio": u["bio"],
            "bot": bool(u["is_bot"]), "nft": nft_of(u), "prem": u["prem_until"] > now(), "lvl": lvl(u["score"]),
            "ver": bool(u["verified"]), "seen": 0 if hs else u["seen"], "hs": hs, "nu": nu_of(u),
            "frozen": fz == 1, "gone": False,
            "av": "/av/%d?v=%d" % (u["id"], u["avts"]) if u["avatar"] else None}


def full(u):
    d = pub(u, True)
    left = 0
    if u["appeal_ts"]:
        left = 999 if admin_ids() else max(1, int(APPEAL_SEC - (now() - u["appeal_ts"])))
    d.update(phone=u["phone"], email=u["email"], email_ok=bool(u["email_ok"]), stars=u["stars"], score=u["score"],
             prev=max(t for t in LV if t <= u["score"]), next=next((t for t in LV if t > u["score"]), None),
             prem_until=u["prem_until"], totp_on=bool(u["totp_on"]), has_key=bool(u["akey"]),
             google=bool(u["gsub"]), bgn=nft_of(u, "nft_bg") or d["nft"], bday=u["bday"],
             hide_seen=bool(u["hide_seen"]), frz_why=u["frz_why"], appeal_left=left, created=u["created"],
             gifts=q("SELECT COUNT(*) c FROM msgs WHERE uid=? AND gift IS NOT NULL", (u["id"],), one=True)["c"])
    return d


def gpub(x):
    n = q("SELECT COUNT(*) c FROM members WHERE g=?", (x["id"],), one=True)["c"]
    if x["frozen"]:  # замороженная группа/канал: «удалена» и недоступна
        nm = "Удалённый канал" if x["kind"] == "channel" else "Удалённая группа"
        return {"id": -x["id"], "nick": "", "uname": "", "desc": "", "name": nm, "av": None, "bot": False,
                "nft": None, "prem": False, "ver": False, "lvl": 0, "seen": 0, "kind": x["kind"], "n": n,
                "gifts": 0, "frozen": True, "gone": True, "hs": False, "bio": "Чат недоступен"}
    gc = q("SELECT COUNT(*) c FROM msgs WHERE gid=? AND gift IS NOT NULL", (x["id"],), one=True)["c"]
    nf = q("SELECT * FROM nftg WHERE id=?", (x["nft"],), one=True) if x["nft"] else None
    un = x["uname"] or ""
    return {"id": -x["id"], "nick": "", "uname": un, "desc": x["bio"], "name": x["title"], "av": None, "bot": False,
            "nft": {"id": nf["id"], "kind": nf["kind"], "anim": nf["anim"]} if nf else None, "prem": False,
            "ver": False, "lvl": 0, "seen": 0, "kind": x["kind"], "n": n, "gifts": gc, "frozen": False,
            "gone": False, "hs": False,
            "bio": "%s · %d уч.%s" % ("Канал" if x["kind"] == "channel" else "Группа", n, " · @" + un if un else "")}


def grp(gid):
    return q("SELECT * FROM grps WHERE id=?", (gid,), one=True) if isinstance(gid, int) else None


def grole(g, uid):  # owner / admin / member / None
    if g["owner"] == uid and ismem(g["id"], uid):
        return "owner"
    r = q("SELECT admin FROM members WHERE g=? AND uid=?", (g["id"], uid), one=True)
    if not r:
        return None
    return "owner" if g["owner"] == uid else ("admin" if r["admin"] else "member")


def ismem(gid, uid):
    return q("SELECT 1 FROM members WHERE g=? AND uid=?", (gid, uid), one=True) is not None


def norm(p):
    p = re.sub(r"[\s\-()]", "", p or "")
    return "+" + p if p.isdigit() else p


def valid_nick(n):
    return re.match(r"^\w{3,20}$", n or "") is not None


def nick_free(n, uid=0):  # юзернейм свободен, только если его нет ни у людей, ни у доп. @, ни у групп
    n = (n or "").strip()
    if n.lower() in RESERVED:
        return False
    return not q("SELECT 1 FROM users WHERE nick=? AND id!=?", (n, uid), one=True) and \
        not q("SELECT 1 FROM unames WHERE name=?", (n,), one=True) and \
        not q("SELECT 1 FROM grps WHERE uname=?", (n,), one=True)


def phone_taken(p, uid=0):
    return q("SELECT 1 FROM users WHERE phone=? AND id!=?", (p, uid), one=True) is not None


def set_av(uid, data):
    if data and data.startswith("data:image/") and len(data) < 700000:
        q("UPDATE users SET avatar=?, avts=? WHERE id=?", (data, int(now()), uid), w=True)


@app.get("/av/<int:uid>")
def avatar(uid):
    u = q("SELECT avatar, frozen FROM users WHERE id=?", (uid,), one=True)
    if not u or not u["avatar"].startswith("data:"):
        return "", 404
    if u["frozen"]:
        cur = me()
        if not (cur and cur["id"] == uid):
            return "", 404
    head, b64 = u["avatar"].split(",", 1)
    r = Response(base64.b64decode(b64), mimetype=head[5:].split(";")[0])
    r.headers["Cache-Control"] = "public, max-age=31536000"
    return r


@app.get("/img/<int:mid>")
def msg_img(mid):  # фото из сообщений (видно только участникам переписки)
    u = me()
    if not u:
        return "", 401
    m = q("SELECT m.frm, m.uid, m.gid, m.img, COALESCE(g.frozen,0) gf FROM msgs m LEFT JOIN grps g ON g.id=m.gid "
          "WHERE m.id=?", (mid,), one=True)
    if not m or not m["img"] or m["gf"]:
        return "", 404
    ok = ismem(m["gid"], u["id"]) if m["gid"] else u["id"] in (m["frm"], m["uid"])
    if not ok:
        return "", 403
    head, b64 = m["img"].split(",", 1)
    r = Response(base64.b64decode(b64), mimetype=head[5:].split(";")[0])
    r.headers["Cache-Control"] = "private, max-age=31536000"
    return r


# ───────── РЕГИСТРАЦИЯ / ВХОД / ВОССТАНОВЛЕНИЕ ─────────
@app.get("/api/phones")
def phones_list():
    taken = {r["phone"] for r in q("SELECT phone FROM users WHERE phone!=''")}
    out = []
    sysf = [p for p in SYSNUMS if p not in taken]  # занятые системные номера не показываем
    if sysf:
        out.append({"fl": "⭐", "n": "Системные номера · без кода · один аккаунт на номер", "items": sysf, "sys": True})
    for fl, n, L in PHONE_GROUPS:
        it = [p for p in L if p not in taken]
        if it:
            out.append({"fl": fl, "n": n, "items": it})
    return jsonify(groups=out)


@app.get("/api/nick/check")
def nick_check():
    n = (request.args.get("n") or "").strip().lstrip("@")
    if hot("nc" + ip(), 60, 60):
        return jsonify(ok=False, msg="Слишком часто, подожди")
    if not valid_nick(n):
        return jsonify(ok=False, msg="3–20 символов: буквы, цифры, _")
    if not nick_free(n):
        return jsonify(ok=False, msg="✗ Этот ник уже занят")
    return jsonify(ok=True, msg="✓ Ник свободен")


@app.post("/api/phone/check")
def phone_check():
    p = norm((request.json or {}).get("phone"))
    if p not in PHONES:
        return err("Этот номер недоступен для регистрации")
    if phone_taken(p):
        return err("Этот номер уже зарегистрирован другим аккаунтом")
    session.pop("phone_ok", None)
    session.pop("phone_wait", None)
    if PHONES[p] is None:
        session["phone_ok"] = p
        return jsonify(need_code=False)
    session["phone_wait"] = p
    return jsonify(need_code=True)


@app.post("/api/phone/verify")
def phone_verify():
    p = session.get("phone_wait")
    if not p or hot("pv" + ip()) or str((request.json or {}).get("code", "")).strip() != str(PHONES.get(p)):
        return err("Неверный код")
    if phone_taken(p):
        return err("Этот номер уже зарегистрирован другим аккаунтом")
    session["phone_ok"] = p
    session.pop("phone_wait")
    return jsonify(ok=True)


@app.post("/api/register")
def register():
    d, ph = request.json or {}, session.get("phone_ok")
    if not ph:
        return err("Сначала подтверди номер телефона")
    if phone_taken(ph):
        session.pop("phone_ok", None)
        return err("Этот номер уже зарегистрирован другим аккаунтом")
    nick, pw = (d.get("nick") or "").strip(), d.get("password") or ""
    if not valid_nick(nick):
        return err("Ник: 3–20 символов, буквы/цифры/_")
    if len(pw) < 6:
        return err("Пароль минимум 6 символов")
    if not nick_free(nick):
        return err("Этот ник уже занят")
    uid = q("INSERT INTO users(nick,pw,name,phone,created) VALUES(?,?,?,?,?)",
            (nick, gph(pw), ((d.get("name") or "").strip() or nick)[:30], ph, now()), w=True)
    set_av(uid, d.get("avatar"))
    new_sess(uid)
    notify(uid, "Привет, %s! 👋 Добро пожаловать в Nova.\nТебе начислено 100 ★. Сюда я буду присылать коды "
                "подтверждения и уведомления.\n\nПопробуй NFT-рулетку во вкладке «Подарки» 🎰 и ежедневный бонус. "
                "@Galochka_bot выдаёт галочку «Проверено NovaGram» ✅\n\n"
                "Если что-то непонятно — пиши мне, я отвечу: /help" % nick)
    return jsonify(ok=True)


def finish_login(u):
    if u["totp_on"]:
        session.clear()
        session["pre"] = u["id"]
        return jsonify(need2fa=True)
    return jsonify(ok=True, restored=new_sess(u["id"]))


def by_nick(n):  # ник ИЛИ номер телефона
    n = (n or "").strip().lstrip("@")
    u = q("SELECT * FROM users WHERE nick=? AND is_bot=0", (n,), one=True)
    if u:
        return u
    p = norm(n)
    if re.match(r"^\+\d{3,15}$", p):
        return q("SELECT * FROM users WHERE phone=? AND is_bot=0", (p,), one=True)
    return None


@app.post("/api/login")
def login():
    d, k = request.json or {}, "l" + ip()
    if locked(k):
        return err("Слишком много неверных попыток, подожди несколько минут", 429)
    u = by_nick(d.get("nick"))
    if not u or not cph(u["pw"], d.get("password") or ""):
        bad(k)
        return err("Неверный ник/номер или пароль")
    _T.pop(k, None)
    return finish_login(u)


@app.post("/api/login/phone")
def login_phone():  # шаг 1 входа по номеру
    p = norm((request.json or {}).get("phone"))
    if hot("lp" + ip(), 8, 300):
        return err("Слишком много попыток, подожди", 429)
    u = q("SELECT * FROM users WHERE phone=? AND is_bot=0", (p,), one=True) if p else None
    if not u:
        return err("Аккаунт с таким номером не найден")
    if PHONES.get(p) is None:  # системный номер: кода нет — вход по паролю
        return jsonify(system=True)
    r = q("SELECT ts FROM codes WHERE uid=? AND kind='plogin'", (u["id"],), one=True)
    if r and now() - r["ts"] < 30:
        return err("Код уже отправлен — открой чат Nova Support в своём аккаунте")
    c = "%05d" % secrets.randbelow(10 ** 5)
    q("DELETE FROM codes WHERE uid=? AND kind='plogin'", (u["id"],), w=True)
    q("INSERT INTO codes(uid,kind,dest,hash,exp,ts) VALUES(?,?,?,?,?,?)",
      (u["id"], "plogin", p, hc(c), now() + 600, now()), w=True)
    notify(u["id"], "📲 Код для входа по номеру %s: %s\nДействует 10 минут. Если это не ты — никому его не сообщай "
                    "и смени пароль." % (p, c))
    return jsonify(ok=True)


@app.post("/api/login/phone/confirm")
def login_phone_confirm():  # шаг 2: код, пришедший сообщением в аккаунт
    d, k = request.json or {}, "lc" + ip()
    if locked(k):
        return err("Слишком много неверных попыток, подожди несколько минут", 429)
    p = norm(d.get("phone"))
    u = q("SELECT * FROM users WHERE phone=? AND is_bot=0", (p,), one=True) if p else None
    if not u or not check_code(u["id"], "plogin", d.get("code", "")):
        bad(k)
        return err("Неверный или просроченный код")
    _T.pop(k, None)
    return finish_login(u)


@app.post("/api/loginkey")
def loginkey():
    d, k = request.json or {}, "l" + ip()
    if locked(k):
        return err("Слишком много неверных попыток, подожди несколько минут", 429)
    u = by_nick(d.get("nick"))
    if not u or not u["akey"] or not cph(u["akey"], (d.get("key") or "").strip().upper()):
        bad(k)
        return err("Неверный ник или ключ доступа")
    _T.pop(k, None)
    return finish_login(u)


@app.post("/api/login2")
def login2():
    u = q("SELECT * FROM users WHERE id=?", (session.get("pre"),), one=True)
    if not u:
        return err("Сессия истекла, войди заново")
    k = "t" + ip()
    if locked(k) or not totp_ok(u["totp"], (request.json or {}).get("code", "")):
        bad(k)
        return err("Неверный код")
    _T.pop(k, None)
    return jsonify(ok=True, restored=new_sess(u["id"]))


@app.post("/api/recover")
def recover():
    n = ((request.json or {}).get("nick") or "").strip()
    if hot("r" + ip(), 6, 600):
        return err("Слишком много попыток, подожди", 429)
    u = by_nick(n) or q("SELECT * FROM users WHERE email=? AND email_ok=1 AND is_bot=0", (n,), one=True)
    if not u:
        return err("Аккаунт не найден")
    if not u["email_ok"] or not u["email"]:
        notify(u["id"], "⚠️ Запрошено восстановление доступа, но код не отправлен: к аккаунту не привязана "
                        "подтверждённая почта.")
        return err("Код не отправлен: к аккаунту не привязана почта")
    e = send_code(u, "recover", u["email"], "Восстановление доступа")
    return err(e) if e else jsonify(ok=True, mask=mask(u["email"]), nick=u["nick"])


@app.post("/api/recover/confirm")
def recover_confirm():
    d = request.json or {}
    u = by_nick(d.get("nick"))
    if not u or hot("rc" + ip(), 10, 600):
        return err("Неверный код")
    if len(d.get("password") or "") < 6:
        return err("Новый пароль минимум 6 символов")
    if not check_code(u["id"], "recover", d.get("code", "")):
        return err("Неверный или просроченный код")
    q("UPDATE users SET pw=? WHERE id=?", (gph(d["password"]), u["id"]), w=True)
    q("DELETE FROM sess WHERE uid=?", (u["id"],), w=True)
    notify(u["id"], "🔑 Пароль аккаунта был изменён через восстановление. Все устройства отключены.")
    return jsonify(ok=True)


@app.post("/api/google")
def google():
    if not GOOGLE_CLIENT_ID:
        return err("Google Client ID не настроен в файле")
    try:
        url = "https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.request.quote(
            (request.json or {}).get("credential", ""))
        info = json.loads(urllib.request.urlopen(url, timeout=10).read())
    except Exception:
        return err("Google отклонил вход")
    if info.get("aud") != GOOGLE_CLIENT_ID:
        return err("Неверный токен")
    u = q("SELECT * FROM users WHERE gsub=?", (info["sub"],), one=True)
    if u:
        return finish_login(u)
    base = re.sub(r"\W", "", (info.get("name") or "user").replace(" ", "_"))[:14] or "user"
    nick = base
    while not nick_free(nick):
        nick = base + str(secrets.randbelow(9999))
    uid = q("INSERT INTO users(nick,pw,name,gsub,created) VALUES(?,?,?,?,?)",
            (nick, gph(secrets.token_hex(8)), info.get("name") or nick, info["sub"], now()), w=True)
    new_sess(uid)
    return jsonify(ok=True)


@app.post("/api/logout")
def logout():
    if session.get("t"):
        q("DELETE FROM sess WHERE tok=?", (h(session["t"]),), w=True)
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def get_me():
    u = me()
    return jsonify(user=full(u) if u else None, gifts=GIFTS, gid=GOOGLE_CLIENT_ID, stickers=STICKERS, nfts=NFTS,
                   anims=ANIMS, sp=SPIN_PRICE, rp=RP, reacts=REACTS, sb=bot_id("SpamBot_Info"), lv=LV, rn=RANKN,
                   sysnums=SYSNUMS)


@app.get("/api/support")
@need_login
def support_id():
    r = q("SELECT id FROM users WHERE nick='novasupport'", one=True)
    return jsonify(id=r["id"] if r else 0)


# ───────── ПРОФИЛЬ И НАСТРОЙКИ ─────────
@app.post("/api/profile")
@need_login
def profile():
    d, u = request.json or {}, me()
    nick = (d.get("nick", u["nick"]) or "").strip()
    if nick != u["nick"]:
        if not valid_nick(nick):
            return err("Ник: 3–20 символов, буквы/цифры/_")
        if not nick_free(nick, u["id"]):
            return err("Этот ник уже занят")
    name = (d.get("name", u["name"]) or "").strip()[:30] or nick
    bday = (d.get("bday", u["bday"]) or "").strip()
    if bday and not re.match(r"^(0[1-9]|[12]\d|3[01])\.(0[1-9]|1[0-2])$", bday):
        return err("День рождения в формате ДД.ММ, например 07.03")
    q("UPDATE users SET nick=?, name=?, bio=?, bday=? WHERE id=?",
      (nick, name, (d.get("bio", u["bio"]) or "")[:120], bday, u["id"]), w=True)
    return jsonify(ok=True)


@app.post("/api/privacy")
@need_login
def privacy():
    d = request.json or {}
    q("UPDATE users SET hide_seen=? WHERE id=?", (1 if d.get("hide_seen") else 0, me()["id"]), w=True)
    return jsonify(ok=True)


@app.post("/api/avatar")
@need_login
def avatar_set():
    set_av(me()["id"], (request.json or {}).get("data"))
    return jsonify(ok=True)


@app.post("/api/password")
@need_login
def password():
    d, u = request.json or {}, me()
    if not u["gsub"] and not cph(u["pw"], d.get("old") or ""):
        return err("Текущий пароль неверный")
    if len(d.get("new") or "") < 6:
        return err("Новый пароль минимум 6 символов")
    q("UPDATE users SET pw=? WHERE id=?", (gph(d["new"]), u["id"]), w=True)
    q("DELETE FROM sess WHERE uid=? AND id!=?", (u["id"], G.sid), w=True)
    return jsonify(ok=True)


@app.post("/api/email")
@need_login
def email():
    u, e = me(), ((request.json or {}).get("email") or "").strip().lower()
    if not e:
        q("UPDATE users SET email='', email_ok=0 WHERE id=?", (u["id"],), w=True)
        return jsonify(ok=True)
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e):
        return err("Некорректная почта")
    if q("SELECT 1 FROM users WHERE email=? AND email_ok=1 AND id!=?", (e, u["id"]), one=True):
        return err("Эта почта уже привязана к другому аккаунту")
    r = send_code(u, "email", e, "Подтверждение почты")
    return err(r) if r else jsonify(sent=True)


@app.post("/api/email/confirm")
@need_login
def email_confirm():
    u = me()
    if hot("e%d" % u["id"], 8, 600):
        return err("Слишком много попыток", 429)
    r = check_code(u["id"], "email", (request.json or {}).get("code", ""))
    if not r:
        return err("Неверный или просроченный код")
    q("UPDATE users SET email=?, email_ok=1 WHERE id=?", (r["dest"], u["id"]), w=True)
    return jsonify(ok=True)


@app.post("/api/phone/change")
@need_login
def phone_change():
    d, u = request.json or {}, me()
    p = norm(d.get("phone"))
    if p not in PHONES:
        return err("Этот номер недоступен")
    if p == u["phone"]:
        return err("Это уже твой номер")
    if phone_taken(p, u["id"]):
        return err("Этот номер уже занят другим аккаунтом")
    if PHONES[p] is not None:
        code = str(d.get("code", "")).strip()
        if not code:
            notify(u["id"], "📲 Подтверждение номера %s\nКод: %s" % (p, PHONES[p]))
            return err("Код отправлен в чат Nova Support — введи его и нажми «Сохранить»")
        if code != str(PHONES[p]):
            return err("Неверный код")
    q("UPDATE users SET phone=? WHERE id=?", (p, u["id"]), w=True)
    return jsonify(ok=True)


@app.post("/api/key")
@need_login
def key_make():
    k = "-".join(secrets.token_hex(2).upper() for _ in range(4))
    q("UPDATE users SET akey=? WHERE id=?", (gph(k), me()["id"]), w=True)
    return jsonify(key=k)


@app.post("/api/key/delete")
@need_login
def key_del():
    q("UPDATE users SET akey=NULL WHERE id=?", (me()["id"],), w=True)
    return jsonify(ok=True)


@app.post("/api/2fa/setup")
@need_login
def tfa_setup():
    sec = base64.b32encode(secrets.token_bytes(10)).decode()
    q("UPDATE users SET totp=?, totp_on=0 WHERE id=?", (sec, me()["id"]), w=True)
    return jsonify(secret=sec)


@app.post("/api/2fa/enable")
@need_login
def tfa_enable():
    u = me()
    if not totp_ok(u["totp"], (request.json or {}).get("code", "")):
        return err("Неверный код")
    q("UPDATE users SET totp_on=1 WHERE id=?", (u["id"],), w=True)
    return jsonify(ok=True)


@app.post("/api/2fa/disable")
@need_login
def tfa_disable():
    u = me()
    if not totp_ok(u["totp"], (request.json or {}).get("code", "")):
        return err("Неверный код")
    q("UPDATE users SET totp_on=0, totp=NULL WHERE id=?", (u["id"],), w=True)
    return jsonify(ok=True)


@app.post("/api/bonus")
@need_login
def bonus():
    u = me()
    if now() - u["bonus_ts"] < 86400:
        return err("Бонус уже получен, приходи завтра")
    q("UPDATE users SET stars=stars+20, bonus_ts=? WHERE id=?", (now(), u["id"]), w=True)
    q("INSERT INTO tx(uid,amount,why,ts) VALUES(?,20,'bonus',?)", (u["id"], now()), w=True)
    return jsonify(ok=True)


@app.post("/api/premium")
@need_login
def premium():
    u, p = me(), PREM.get((request.json or {}).get("plan"))
    if not p:
        return err("Нет такого тарифа")
    if not spend(u["id"], p[0], "premium"):
        return err("Не хватает звёзд ★")
    until = max(now(), u["prem_until"]) + p[1] * 86400
    q("UPDATE users SET prem_until=? WHERE id=?", (until, u["id"]), w=True)
    notify(u["id"], "⭐ Premium активен до %s. Спасибо!" % time.strftime("%d.%m.%Y", time.localtime(until)))
    return jsonify(ok=True)


def purge_user(uid):
    """Окончательное удаление аккаунта. Группы переходят другому участнику."""
    for g in q("SELECT * FROM grps WHERE owner=?", (uid,)):
        nx = q("SELECT uid FROM members WHERE g=? AND uid!=? ORDER BY admin DESC, rowid LIMIT 1", (g["id"], uid), one=True)
        if nx:
            q("UPDATE grps SET owner=?, nft=0 WHERE id=?", (nx["uid"], g["id"]), w=True)
            q("UPDATE members SET admin=0 WHERE g=? AND uid=?", (g["id"], nx["uid"]), w=True)
            notify(nx["uid"], "👑 Владелец «%s» удалил аккаунт — теперь владелец ты." % g["title"])
    q("UPDATE grps SET nft=0 WHERE nft IN (SELECT id FROM nftg WHERE uid=?)", (uid,), w=True)
    for t in ("rdst", "pins", "mutes", "clr", "arch"):
        q("DELETE FROM %s WHERE uid=? OR peer=?" % t, (uid, uid), w=True)
    q("DELETE FROM users WHERE id=?", (uid,), w=True)  # каскадом уходят сессии, NFT, юзернеймы, боты, сообщения


@app.post("/api/account/delete")
@need_login
def account_delete():
    d, u = request.json or {}, me()
    k = "d%d" % u["id"]
    if locked(k, 5, 600):
        return err("Слишком много неверных попыток, подожди", 429)
    if (d.get("word") or "").strip().upper() != "УДАЛИТЬ":
        bad(k)
        return err("Напиши слово УДАЛИТЬ для подтверждения")
    if not u["gsub"] and not cph(u["pw"], d.get("password") or ""):
        bad(k)
        return err("Неверный пароль")
    if u["totp_on"] and not totp_ok(u["totp"], d.get("code", "")):
        bad(k)
        return err("Неверный код двухэтапной защиты")
    uid, instant = u["id"], bool(d.get("now"))
    if instant:
        purge_user(uid)
    else:  # отложенное удаление: аккаунт выглядит удалённым, а вход в течение DEL_DAYS дней возвращает его
        q("UPDATE users SET frozen=2, del_at=?, appeal_ts=0 WHERE id=?", (now() + DEL_DAYS * 86400, uid), w=True)
        q("DELETE FROM sess WHERE uid=?", (uid,), w=True)
    session.clear()
    return jsonify(ok=True, instant=instant, days=DEL_DAYS)


@app.get("/api/devices")
@need_login
def devices():
    u, n = me(), now()
    return jsonify(items=[dict(id=r["id"], device=r["device"], ip=r["ip"], seen=r["seen"], cur=r["id"] == G.sid,
                               place=", ".join(x for x in (r["city"], r["country"]) if x),
                               online=r["id"] == G.sid or n - r["seen"] < 75)
                          for r in q("SELECT * FROM sess WHERE uid=? ORDER BY seen DESC", (u["id"],))])


@app.post("/api/devices/info")
@need_login
def devices_info():
    m = re.sub(r"[^\w .+\-/]", "", str((request.json or {}).get("model") or ""))[:40].strip()
    if m:
        br = dev(request.headers.get("User-Agent", "")).split(" · ")[-1]
        q("UPDATE sess SET device=? WHERE id=?", (m + " · " + br, G.sid), w=True)
    return jsonify(ok=True)


@app.post("/api/devices/kill")
@need_login
def devices_kill():
    d, u = request.json or {}, me()
    if d.get("all"):
        q("DELETE FROM sess WHERE uid=? AND id!=?", (u["id"], G.sid), w=True)
    else:
        q("DELETE FROM sess WHERE id=? AND uid=? AND id!=?", (d.get("id"), u["id"], G.sid), w=True)
    return jsonify(ok=True)


# ───────── NFT: РУЛЕТКА, НОСКА, ФОН ─────────
@app.get("/api/nft")
@need_login
def nft_mine():
    u = me()
    return jsonify(items=[dict(id=r["id"], kind=r["kind"], anim=r["anim"], eq=r["id"] == u["nft_eq"],
                               bg=r["id"] == u["nft_bg"])
                          for r in q("SELECT * FROM nftg WHERE uid=? ORDER BY id DESC", (u["id"],))])


@app.post("/api/nft/spin")
@need_login
def nft_spin():
    u = me()
    if not spend(u["id"], SPIN_PRICE, "nft spin"):
        return err("Не хватает звёзд ★")
    n = secrets.SystemRandom().choices(NFTS, [x["w"] for x in NFTS])[0]
    nid = q("INSERT INTO nftg(uid,kind,ts) VALUES(?,?,?)", (u["id"], n["id"], now()), w=True)
    a, b = add_score(u["id"], RP[n["r"]])
    return jsonify(id=nid, kind=n["id"], pts=RP[n["r"]], lvl=b, up=b > a)


@app.post("/api/nft/anim")
@need_login
def nft_anim():
    d = request.json or {}
    if d.get("anim") not in AMAP:
        return err("Нет такой анимации")
    q("UPDATE nftg SET anim=? WHERE id=? AND uid=?", (d["anim"], d.get("id"), me()["id"]), w=True)
    return jsonify(ok=True)


def _wear(col, other):
    # в профиле может быть ТОЛЬКО ОДНО: NFT рядом с ником, NFT-узор по бокам или NFT-юзернейм
    u, i = me(), (request.json or {}).get("id") or 0
    if i and not q("SELECT 1 FROM nftg WHERE id=? AND uid=?", (i, u["id"]), one=True):
        return err("Это не твой NFT")
    if i:
        q("UPDATE users SET %s=?, %s=0, nu_show='' WHERE id=?" % (col, other), (i, u["id"]), w=True)
    else:
        q("UPDATE users SET %s=0 WHERE id=?" % col, (u["id"],), w=True)
    return jsonify(ok=True)


@app.post("/api/nft/equip")
@need_login
def nft_equip():  # справа от ника + цвет фона профиля
    return _wear("nft_eq", "nft_bg")


@app.post("/api/nft/bg")
@need_login
def nft_bg():  # узор NFT по бокам профиля
    return _wear("nft_bg", "nft_eq")


# ───────── ЮЗЕРНЕЙМЫ И БОТЫ ─────────
@app.get("/api/unames")
@need_login
def unames():
    u = me()
    return jsonify(items=[dict(name=r["name"], nft=bool(r["nft"]), show=r["name"] == u["nu_show"]) for r in
                          q("SELECT * FROM unames WHERE uid=? ORDER BY nft DESC, name", (u["id"],))])


@app.post("/api/unames/add")
@need_login
def unames_add():
    u = me()
    n = ((request.json or {}).get("name") or "").strip().lstrip("@").lower()
    if not valid_nick(n):
        return err("Юзернейм: 3–20 символов, буквы/цифры/_")
    if q("SELECT COUNT(*) c FROM unames WHERE uid=?", (u["id"],), one=True)["c"] >= 5:
        return err("Максимум 5 дополнительных юзернеймов")
    if not nick_free(n):
        return err("Этот юзернейм занят — его можно взять только когда он освободится")
    q("INSERT INTO unames(name,uid) VALUES(?,?)", (n, u["id"]), w=True)
    return jsonify(ok=True)


@app.post("/api/unames/del")
@need_login
def unames_del():
    q("DELETE FROM unames WHERE name=? AND uid=? AND nft=0", ((request.json or {}).get("name"), me()["id"]), w=True)
    return jsonify(ok=True)


@app.post("/api/unames/wear")
@need_login
def unames_wear():
    u, n = me(), ((request.json or {}).get("name") or "").strip().lower()
    if not n:
        q("UPDATE users SET nu_show='' WHERE id=?", (u["id"],), w=True)
        return jsonify(ok=True)
    if not q("SELECT 1 FROM unames WHERE name=? AND uid=? AND nft=1", (n, u["id"]), one=True):
        return err("Это не твой NFT-юзернейм")
    q("UPDATE users SET nu_show=?, nft_eq=0, nft_bg=0 WHERE id=?", (n, u["id"]), w=True)
    return jsonify(ok=True)


@app.get("/api/bots")
@need_login
def bots_list():
    return jsonify(items=[dict(id=b["id"], nick=b["nick"], name=b["name"],
                               cmds=[dict(trig=c["trig"], reply=c["reply"]) for c in
                                     q("SELECT * FROM bcmd WHERE bot=?", (b["id"],))])
                          for b in q("SELECT * FROM users WHERE is_bot=1 AND owner=?", (me()["id"],))])


@app.post("/api/bots/new")
@need_login
def bots_new():
    d, u = request.json or {}, me()
    nick, name = (d.get("nick") or "").strip().lstrip("@"), (d.get("name") or "").strip()[:30]
    if not valid_nick(nick) or not nick.lower().endswith("bot"):
        return err("Юзернейм бота должен заканчиваться на bot")
    if not name:
        return err("Введи имя бота")
    if not nick_free(nick):
        return err("Этот юзернейм занят")
    q("INSERT INTO users(nick,pw,name,bio,is_bot,owner,created) VALUES(?,?,?,?,1,?,?)",
      (nick, gph(secrets.token_hex(16)), name, (d.get("desc") or "")[:120], u["id"], now()), w=True)
    return jsonify(ok=True)


@app.post("/api/bots/cmd")
@need_login
def bots_cmd():
    d = request.json or {}
    trig, rep = (d.get("trig") or "").strip()[:40], (d.get("reply") or "").strip()[:500]
    if not q("SELECT 1 FROM users WHERE id=? AND owner=? AND is_bot=1", (d.get("bot"), me()["id"]), one=True):
        return err("Это не твой бот")
    if not trig or not rep:
        return err("Заполни команду и ответ")
    q("INSERT INTO bcmd(bot,trig,reply) VALUES(?,?,?)", (d["bot"], trig, rep), w=True)
    return jsonify(ok=True)


def nft_bot(b, u, t):
    uid, me_ = u["id"], b["id"]
    if t == "/start":
        mine = [r["name"] for r in q("SELECT name FROM unames WHERE uid=? AND nft=0", (uid,))]
        if not mine:
            return say(me_, uid, "💎 Nova NFT\n\nУ тебя нет обычных доп. юзернеймов.\n"
                                 "Добавь их в Настройки → Мои юзернеймы и вернись: /start")
        q("INSERT OR REPLACE INTO bstate(uid) VALUES(?)", (uid,), w=True)
        return say(me_, uid, "💎 Nova NFT\n\nПревращаю юзернеймы в NFT (%d ★, +%d очков ранга). NFT нельзя удалить.\n\n"
                             "Твои юзернеймы:\n%s\n\nОтправь юзернейм (без @)." %
                   (NFT_NAME_PRICE, NFT_NAME_PTS, "\n".join("@" + n for n in mine)))
    if not q("SELECT 1 FROM bstate WHERE uid=?", (uid,), one=True):
        return say(me_, uid, "Нажми /start, чтобы начать 🙂")
    name = t.lstrip("@").lower()
    r = q("SELECT * FROM unames WHERE name=? AND uid=?", (name, uid), one=True)
    if not r:
        return say(me_, uid, "Это не твой юзернейм. Отправь один из своих или /start")
    if r["nft"]:
        return say(me_, uid, "@%s уже NFT 💎" % name)
    if not spend(uid, NFT_NAME_PRICE, "nft username"):
        return say(me_, uid, "Не хватает звёзд: нужно %d ★" % NFT_NAME_PRICE)
    q("UPDATE unames SET nft=1 WHERE name=?", (name,), w=True)
    q("DELETE FROM bstate WHERE uid=?", (uid,), w=True)
    cur = q("SELECT nft_eq, nft_bg, nu_show FROM users WHERE id=?", (uid,), one=True)
    if not cur["nft_eq"] and not cur["nft_bg"] and not cur["nu_show"]:  # в профиле пусто — ставим автоматически
        q("UPDATE users SET nu_show=? WHERE id=?", (name, uid), w=True)
    say(me_, uid, "🎉 Готово! @%s теперь NFT 💎\nОчки ранга: +%d" % (name, NFT_NAME_PTS))
    add_score(uid, NFT_NAME_PTS)


def galochka_bot(b, u, t):
    uid, me_, c = u["id"], b["id"], t.lower()
    if c == "/get":
        if u["verified"]:
            return say(me_, uid, "У тебя уже есть галочка ✅")
        q("UPDATE users SET verified=1 WHERE id=?", (uid,), w=True)
        return say(me_, uid, "✅ Готово! Рядом с твоим именем появилась галочка «Проверено NovaGram».")
    if c == "/remove":
        q("UPDATE users SET verified=0 WHERE id=?", (uid,), w=True)
        return say(me_, uid, "Галочка убрана. Вернуть её можно командой /get")
    say(me_, uid, "✅ Galochka\n\nЯ выдаю галочку «Проверено NovaGram» — она показывается слева от твоего имени.\n\n"
                  "/get — получить галочку\n/remove — убрать галочку")


# ───────── RATRA_BOT: МОДЕРАТОР ─────────
RATRA_MENU = ("🐀 Ratra — модератор NovaGram\n\nЯ блокирую нарушителей. Пришли юзернейм того, кого нужно "
              "заблокировать — аккаунт, группу, канал или бота. Можно сразу с причиной:\n"
              "@username спам в личках\n\n"
              "❄️ Аккаунт замораживается: имя превращается в «Удалённый аккаунт», писать, тратить ★ и менять "
              "настройки он больше не сможет. Писать можно только в @SpamBot_Info.\n"
              "❄️ Группа или канал становятся недоступными для всех участников.\n\n"
              "/block @юзернейм [причина] — заблокировать\n/unblock @юзернейм — разблокировать (только своё)\n"
              "/list — мои блокировки\n/stats — статистика")
_RM = {}  # uid -> True, если следующим сообщением надо РАЗблокировать


def freeze_msg(x, why):
    return ("❄️ Твой аккаунт заморожен за нарушение правил сообщества NovaGram.\n\n"
            "📋 Причина: %s\n🕒 Дата: %s\n🆔 Обращение: #FZ-%d\n\n"
            "Пока он заморожен, ты не можешь писать сообщения, тратить ★ и менять настройки. Писать можно только мне.\n\n"
            "Как подать апелляцию:\n1️⃣ Напиши мне одним сообщением, почему аккаунт нужно разблокировать\n"
            "2️⃣ Отправь /appeal — апелляция уйдёт модератору, ответ придёт сюда\n\nПравила: /rules" %
            (why or "нарушение правил сообщества", time.strftime("%d.%m.%Y %H:%M", time.localtime(now())), x["id"]))


def split_t(s):
    p = (s or "").strip().split(None, 1)
    return (p[0] if p else ""), (p[1].strip()[:120] if len(p) > 1 else "")


def find_target(name):
    n = (name or "").strip().lstrip("@")
    n = n.split()[0] if n else ""
    if not n:
        return None
    r = q("SELECT id FROM users WHERE nick=?", (n,), one=True) or q("SELECT uid AS id FROM unames WHERE name=?", (n,), one=True)
    if r:
        return ("u", r["id"])
    g = q("SELECT id FROM grps WHERE uname=?", (n,), one=True)
    return ("g", g["id"]) if g else None


def ratra_bot(b, u, t):
    uid, me_ = u["id"], b["id"]
    c = t.strip()
    low = c.lower()
    if low in ("", "/start", "/help"):
        return say(me_, uid, RATRA_MENU)
    if low == "/stats":
        fu = q("SELECT COUNT(*) c FROM users WHERE frozen=1", one=True)["c"]
        fg = q("SELECT COUNT(*) c FROM grps WHERE frozen=1", one=True)["c"]
        ap = q("SELECT COUNT(*) c FROM users WHERE frozen=1 AND appeal_ts>0", one=True)["c"]
        mine = q("SELECT COUNT(*) c FROM users WHERE frozen=1 AND blk_by=?", (uid,), one=True)["c"]
        return say(me_, uid, "📊 Статистика модерации\n\n❄️ Замороженных аккаунтов: %d\n❄️ Замороженных чатов: %d\n"
                             "📨 Апелляций на рассмотрении: %d\n👤 Заморожено тобой: %d" % (fu, fg, ap, mine))
    if low == "/list":
        us = q("SELECT nick, frz_why, appeal_ts FROM users WHERE frozen=1 AND blk_by=?", (uid,))
        gs = q("SELECT COALESCE(uname,'') un, title FROM grps WHERE frozen=1 AND blk_by=?", (uid,))
        if not us and not gs:
            return say(me_, uid, "Ты пока никого не блокировал 🙂")
        rows = ["❄️ @%s%s%s" % (r["nick"], " — " + r["frz_why"] if r["frz_why"] else "",
                                " · 📨 апелляция" if r["appeal_ts"] else "") for r in us] + \
               ["❄️ %s%s" % (r["title"], " (@%s)" % r["un"] if r["un"] else "") for r in gs]
        return say(me_, uid, "Твои блокировки:\n" + "\n".join(rows))
    cmd, _, arg = c.partition(" ")
    cl = cmd.lower()
    if cl in ("/block", "/unblock"):
        un = cl == "/unblock"
        if not arg.strip():
            _RM[uid] = un
            return say(me_, uid, "Отправь юзернейм того, кого нужно %s (например @username)%s." %
                       ("разблокировать" if un else "заблокировать", "" if un else " и, если хочешь, причину"))
        _RM.pop(uid, None)
        target = arg
    elif cl.startswith("/"):
        return say(me_, uid, "Не знаю такой команды 🤔 Список: /help")
    else:
        un, target = _RM.pop(uid, False), c
    if hot("rt%d" % uid, 12, 600):
        return say(me_, uid, "⏳ Слишком много запросов. Подожди пару минут.")
    name, why = split_t(target)
    tg = find_target(name)
    if not tg:
        return say(me_, uid, "🔍 Не нашла такой юзернейм. Проверь написание и отправь ещё раз.")
    kind, tid = tg
    if kind == "u":
        x = q("SELECT * FROM users WHERE id=?", (tid,), one=True)
        if x["id"] == uid:
            return say(me_, uid, "Себя заблокировать нельзя 🙂")
        if x["is_bot"] and x["owner"] is None:
            return say(me_, uid, "🛡 Это системный бот Nova — его блокировать нельзя.")
        if x["frozen"] == 2:
            return say(me_, uid, "Этот аккаунт уже удалён владельцем 🗑")
        if un:
            if not x["frozen"]:
                return say(me_, uid, "@%s не заблокирован." % x["nick"])
            if x["blk_by"] != uid:
                return say(me_, uid, "Разблокировать может только тот, кто заблокировал. "
                                     "Пользователь может подать апелляцию в @SpamBot_Info.")
            unfreeze_user(x["id"], "mod")
            return say(me_, uid, "✅ @%s разблокирован." % x["nick"])
        if x["frozen"]:
            return say(me_, uid, "@%s уже заморожен ❄️" % x["nick"])
        q("UPDATE users SET frozen=1, blk_by=?, frz_ts=?, frz_why=?, appeal_ts=0, appeal_txt='' WHERE id=?",
          (uid, now(), why, x["id"]), w=True)
        sb = bot_id("SpamBot_Info")
        if sb:
            say(sb, x["id"], freeze_msg(x, why))
        return say(me_, uid, "❄️ Готово! @%s заморожен%s: теперь это «Удалённый аккаунт», писать и тратить ★ он не может.\n"
                             "Вернуть: /unblock @%s" % (x["nick"], " (причина: %s)" % why if why else "", x["nick"]))
    x = q("SELECT * FROM grps WHERE id=?", (tid,), one=True)
    kn = "Канал" if x["kind"] == "channel" else "Группа"
    if un:
        if not x["frozen"]:
            return say(me_, uid, "«%s» не заблокирован(а)." % x["title"])
        if x["blk_by"] != uid:
            return say(me_, uid, "Разблокировать может только тот, кто заблокировал.")
        q("UPDATE grps SET frozen=0, blk_by=0 WHERE id=?", (x["id"],), w=True)
        say(me_, x["owner"], "✅ «%s» снова доступен(а). Ограничения сняты." % x["title"])
        return say(me_, uid, "✅ %s «%s» разблокирован(а)." % (kn, x["title"]))
    if x["frozen"]:
        return say(me_, uid, "«%s» уже заблокирован(а) ❄️" % x["title"])
    q("UPDATE grps SET frozen=1, blk_by=? WHERE id=?", (uid, x["id"]), w=True)
    if x["owner"] != uid:
        say(me_, x["owner"], "❄️ Твой чат «%s» заблокирован за нарушение правил сообщества NovaGram%s. "
                             "Он больше недоступен участникам." % (x["title"], " (причина: %s)" % why if why else ""))
    say(me_, uid, "❄️ Готово! %s «%s» заблокирован(а) и теперь недоступен(а) для всех.\nВернуть: /unblock @%s" %
        (kn, x["title"], x["uname"] or "юзернейм"))


# ───────── SPAM BOT INFO: ЗАМОРОЗКА / АПЕЛЛЯЦИИ ─────────
RULES = ("📜 Правила сообщества NovaGram\n\n1. Не спамь и не рассылай одинаковые сообщения незнакомым.\n"
         "2. Не оскорбляй и не угрожай другим пользователям.\n3. Не выдавай себя за других и за модераторов.\n"
         "4. Не распространяй мошеннические ссылки и запрещённый контент.\n5. Не обманывай систему ★ и рейтинга.\n\n"
         "За нарушение аккаунт замораживается ❄️. Если это ошибка — напиши мне объяснение и отправь /appeal.")
SPAM_MENU = ("🛡 Spam Bot Info\n\nЯ отвечаю за заморозку и разморозку аккаунтов NovaGram.\n\n"
             "/status — состояние аккаунта\n/rules — правила\n\nЕсли аккаунт заморожен: напиши мне, почему его нужно "
             "разблокировать, и отправь /appeal.")


def unfreeze_user(uid, by="appeal", note=""):
    if q("UPDATE users SET frozen=0, blk_by=0, appeal_ts=0, appeal_txt='', frz_why='', frz_ts=0 "
         "WHERE id=? AND frozen=1", (uid,), w=True):
        sb = bot_id("SpamBot_Info")
        if sb:
            if by == "mod":
                say(sb, uid, "✅ Модератор снял ограничения — аккаунт разморожен. Можно снова писать, дарить подарки "
                             "и пользоваться Nova!")
            elif by == "human":
                say(sb, uid, "✅ Апелляция одобрена! Модератор Nova Support (@novasupport) разморозил аккаунт.%s\n\n"
                             "Можно снова писать и пользоваться Nova. Соблюдай правила 🙏 (/rules)" %
                    ("\n💬 Модератор написал: «%s»" % note if note else ""))
            else:
                say(sb, uid, "✅ Апелляция одобрена! Твой аккаунт разморожен — можно снова писать, дарить подарки "
                             "и пользоваться Nova. Соблюдай правила сообщества 🙏 (/rules)")
        return True
    return False


def spam_bot(b, u, t):
    uid, me_, raw = u["id"], b["id"], (t or "").strip()
    c = re.sub(r"^(/\w+)@\w+", r"\1", raw.lower())
    if u["frozen"] != 1:
        if c in ("/start", "/help", ""):
            return say(me_, uid, SPAM_MENU)
        if c == "/rules":
            return say(me_, uid, RULES)
        if c == "/status":
            return say(me_, uid, "✅ С твоим аккаунтом всё хорошо — никаких ограничений нет.\n"
                                 "📅 В Nova с %s\n📨 Апелляций подано: %d" %
                       (time.strftime("%d.%m.%Y", time.localtime(u["created"] or now())), u["appeals"]))
        return say(me_, uid, "✅ Ограничений нет. Команды: /status, /rules")
    t0, human = u["appeal_ts"], bool(admin_ids())
    if t0 and not human and now() - t0 >= APPEAL_SEC:
        return unfreeze_user(uid)
    left = max(1, int(APPEAL_SEC - (now() - t0))) if t0 else 0
    wait = "⏳ Апелляция у модератора Nova Support — ожидай ответа здесь." if human else \
        "⏳ Апелляция проверяется, осталось примерно %d сек." % left
    if c == "/rules":
        return say(me_, uid, RULES)
    if c == "/appeal":
        if t0:
            return say(me_, uid, wait)
        txt = u["appeal_txt"]
        if not txt:
            return say(me_, uid, "✍️ Сначала напиши мне одним сообщением, почему твой аккаунт нужно разблокировать "
                                 "(что произошло и почему это ошибка). Потом снова отправь /appeal.")
        q("UPDATE users SET appeal_ts=?, appeals=appeals+1 WHERE id=?", (now(), uid), w=True)
        if human:
            sup = bot_id("novasupport")
            for aid in admin_ids():
                say(sup, aid, "📨 Новая апелляция #%d\n👤 @%s (%s)\n📋 Причина заморозки: %s\n💬 Пользователь написал:\n«%s»\n\n"
                              "/approve %d [комментарий] — разморозить\n/deny %d [комментарий] — отклонить\n/appeals — список" %
                    (uid, u["nick"], u["name"], u["frz_why"] or "нарушение правил", txt, uid, uid))
            return say(me_, uid, "📨 Апелляция отправлена человеку — модератору Nova Support (@novasupport).\n\n"
                                 "💬 Ты написал:\n«%s»\n\nОтвет придёт сюда." % txt)
        return say(me_, uid, "📨 Апелляция принята!\n\n💬 Ты написал:\n«%s»\n\nПроверка займёт около %d секунд — "
                             "я напишу, как только будет решение." % (txt, APPEAL_SEC))
    if c in ("/status", "/why"):
        return say(me_, uid, "❄️ Аккаунт заморожен\n📋 Причина: %s\n🕒 С %s\n📨 Апелляций подано: %d\n✍️ Твоё объяснение: %s\n\n%s" % (
            u["frz_why"] or "нарушение правил сообщества",
            time.strftime("%d.%m.%Y %H:%M", time.localtime(u["frz_ts"] or now())), u["appeals"],
            "«%s»" % u["appeal_txt"] if u["appeal_txt"] else "не написано",
            wait if t0 else "Напиши, почему нужно разблокировать, и отправь /appeal"))
    if not raw:
        return say(me_, uid, "Напиши объяснение текстом ✍️")
    if not raw.startswith("/"):
        if t0:
            return say(me_, uid, wait)
        q("UPDATE users SET appeal_txt=? WHERE id=?", (raw[:500], uid), w=True)
        return say(me_, uid, "✍️ Записала твоё объяснение:\n«%s»\n\nТеперь отправь /appeal. Хочешь изменить текст — "
                             "просто напиши новое сообщение." % raw[:500])
    say(me_, uid, "❄️ Твой аккаунт заморожен.\n\n1️⃣ Напиши, почему его нужно разблокировать\n2️⃣ Отправь /appeal\n\n"
                  "/status — состояние\n/rules — правила")


# ───────── NOVA SUPPORT ─────────
SUP_MENU = ("🛟 Nova Support\n\nПривет! Я помогу с самыми частыми вопросами. Нажми тему или напиши своими словами:\n\n"
            "/password — пароль и вход\n/nft — NFT и юзернеймы\n/ranks — ранги и рейтинг\n"
            "/verify — галочка\n/email — почта и коды\n/features — возможности чатов\n"
            "/delete — удаление аккаунта\n/tickets — мои обращения\n\nЕсли ничего не подошло — опиши проблему, "
            "я создам обращение, или напиши /ticket текст.")
SUP = [
    (("/password", "парол", "не могу войти", "забыл", "взлом", "по номеру"),
     "🔑 Пароль и вход\n• Забыл пароль: на экране входа нажми «Забыл пароль?» — код придёт на подтверждённую почту.\n"
     "• Вход по номеру: на экране входа «📱 Войти по номеру» — код придёт сообщением сюда, в чат Nova Support "
     "(на другом твоём устройстве). Системные номера без кода входят по паролю.\n"
     "• Сменить пароль: Настройки → Пароль.\n• Вход без пароля: Настройки → Ключ доступа.\n"
     "• Защита: двухэтапная защита в Настройки → Двухэтапная защита."),
    (("/stars", "звезд", "звёзд", "баланс", "★", "бонус"),
     "★ Звёзды\n• Ежедневный бонус +20 ★ — вкладка «Подарки».\n• Звёзды тратятся на подарки, NFT-рулетку и Premium."),
    (("/nft", "nft", "нфт", "рулетк", "юзернейм", "username"),
     "💎 NFT и юзернеймы\n• Рулетка: вкладка «Подарки» (100 ★) — выпадают NFT и очки ранга.\n• В профиле показывается "
     "что-то ОДНО: NFT рядом с ником, NFT-узор по бокам или NFT-юзернейм — новое заменяет прежнее.\n"
     "• NFT-юзернейм делает @Nova_NFT_bot: сначала добавь @ в Настройки → Мои юзернеймы.\n"
     "• Занятый юзернейм взять нельзя, пока он не освободится."),
    (("/ranks", "ранг", "рейтинг", "очки"),
     "🏅 Ранги и рейтинг\nВсего %d рангов: " % len(LV) + " → ".join("%s (%d)" % (RANKN[i], LV[i]) for i in range(len(LV))) +
     ".\nОчки дают NFT-рулетка (40–500) и NFT-юзернеймы (+150). Нажми на значок ранга рядом с именем — увидишь все ступени."),
    (("/verify", "галочк", "проверен"),
     "✅ Галочка «Проверено NovaGram»\nЗабери её у @Galochka_bot командой /get (убрать — /remove)."),
    (("/email", "почт", "письм", "код не прих"),
     "📧 Почта\nНастройки → Почта → введи адрес → код придёт письмом (копия — сюда). Если письма нет: проверь «Спам», "
     "подожди минуту и отправь код снова."),
    (("/delete", "удалить акк", "удаление", "удалить профиль"),
     "🗑 Удаление аккаунта\nНастройки → внизу «Удалить аккаунт». Нужны пароль, слово УДАЛИТЬ (и код 2FA, если включена).\n"
     "• Обычное удаление — через %d дней. Всё это время можно передумать: просто войди снова.\n"
     "• «Удалить сразу» — мгновенно и навсегда: пропадут сообщения, NFT, звёзды и юзернеймы.\n"
     "Группы, где ты владелец, перейдут другому участнику." % DEL_DAYS),
    (("/privacy", "приватн", "в сети", "последн", "скрыть"),
     "🔒 Приватность\nНастройки → Конфиденциальность: можно скрыть «был(а) в сети» — другие увидят «был(а) недавно». "
     "Там же список заблокированных пользователей."),
    (("/features", "функци", "перес", "реакц", "ответить", "черновик", "mute", "заглуш", "поиск", "закреп", "архив", "очист"),
     "💬 Возможности чатов\n• Нажми на сообщение: реакции, ответ, пересылка, закреп 📌, копирование, правка, удаление.\n"
     "• Меню чата ⋮: поиск по чату 🔍, закрепить чат, заглушить 🔕, в архив 📥, очистить историю, заблокировать.\n"
     "• Папки чатов над списком (в том числе «Архив»).\n• Черновики сохраняются сами. • «печатает…» и ✓✓ прочитано.\n"
     "• Фон чата: Настройки → Фон чата."),
    (("заблокировать пользов", "чёрный список", "черный список", "заблокировал"),
     "🚫 Заблокировать пользователя\nОткрой чат → ⋮ → «Заблокировать». Он больше не сможет писать тебе. "
     "Список блокировок: Настройки → Конфиденциальность."),
    (("/frozen", "заморож", "заблок", "блокир", "апелл"),
     "❄️ Заморозка и блокировки\nЕсли аккаунт заморожен — напиши @SpamBot_Info: сначала объясни, почему аккаунт нужно "
     "разблокировать, затем отправь /appeal — апелляция уйдёт модератору, ответ придёт туда же. Правила: /rules. "
     "Заблокировать нарушителя можно через @Ratra_bot."),
    (("/groups", "групп", "канал", "админ", "владел"),
     "👥 Группы и каналы\nОткрой группу → нажми на её название: там участники, подарки и настройки. Владелец может "
     "менять название, ставить @юзернейм, вешать NFT, назначать админов и передавать владение."),
    (("/photo", "фото", "картинк", "изображен"),
     "🖼 Фото\nВ чате нажми кнопку с картинкой слева от поля ввода, выбери снимок из галереи, добавь подпись и отправь. "
     "Нажми на фото в чате, чтобы открыть его на весь экран."),
    (("/premium", "premium", "премиум"),
     "⭐ Premium\nНастройки → Premium: 50 ★ в месяц или 100 ★ в год. Звезда рядом с твоим именем."),
    (("привет", "здравств", "добрый", "hello"),
     "Привет! 👋 Чем могу помочь? Выбери тему: /help"),
    (("спасибо", "благодар", "thanks"),
     "Всегда рада помочь! 🥰 Если появятся вопросы — пиши."),
]


def support_admin(b, u, raw):
    """Команды человека-модератора (ники из ADMINS) — работают в чате с @novasupport."""
    uid, me_ = u["id"], b["id"]
    parts = raw.split(None, 2)
    cmd = parts[0].lower()
    if cmd == "/appeals":
        rows = q("SELECT id,nick,appeal_txt FROM users WHERE frozen=1 AND appeal_ts>0 ORDER BY appeal_ts")
        if not rows:
            return say(me_, uid, "📭 Апелляций на рассмотрении нет.")
        return say(me_, uid, "📨 Апелляции:\n" + "\n".join("#%d @%s — %s" % (r["id"], r["nick"], r["appeal_txt"][:70])
                                                          for r in rows))
    if len(parts) < 2 or not parts[1].lstrip("#").isdigit():
        return say(me_, uid, "Формат: %s НОМЕР [комментарий], например %s 5 всё в порядке" % (cmd, cmd))
    x = q("SELECT * FROM users WHERE id=?", (int(parts[1].lstrip("#")),), one=True)
    note = parts[2].strip()[:300] if len(parts) > 2 else ""
    if not x or x["frozen"] != 1:
        return say(me_, uid, "Такого замороженного аккаунта нет.")
    if cmd == "/approve":
        unfreeze_user(x["id"], "human", note)
        return say(me_, uid, "✅ @%s разморожен. Пользователю отправлен ответ." % x["nick"])
    q("UPDATE users SET appeal_ts=0, appeal_txt='' WHERE id=?", (x["id"],), w=True)
    sb = bot_id("SpamBot_Info")
    if sb:
        say(sb, x["id"], "❌ Апелляция отклонена модератором Nova Support (@novasupport).%s\n\nЕсли хочешь — напиши новое "
                         "объяснение и снова отправь /appeal." % ("\n💬 Модератор написал: «%s»" % note if note else ""))
    say(me_, uid, "❌ Апелляция @%s отклонена. Пользователю отправлен ответ." % x["nick"])


def support_bot(b, u, t, gift):
    uid, me_, raw = u["id"], b["id"], (t or "").strip()
    c = re.sub(r"^(/\w+)@\w+", r"\1", raw.lower())
    if gift:
        return say(me_, uid, "Спасибо за подарок! 🥰")
    if not c:
        return say(me_, uid, "Классный стикер 😄 Если нужна помощь — жми /help")
    if c.split()[0] in ("/approve", "/deny", "/appeals") and uid in admin_ids():
        return support_admin(b, u, re.sub(r"^(/\w+)@\w+", r"\1", raw))
    if c in ("/start", "/help", "помощь", "меню", "help"):
        return say(me_, uid, SUP_MENU)
    if c.startswith("/tickets"):
        rows = q("SELECT id,text,ts FROM tickets WHERE uid=? ORDER BY id DESC LIMIT 5", (uid,))
        if not rows:
            return say(me_, uid, "У тебя пока нет обращений. Опиши проблему — я создам первое 📝")
        return say(me_, uid, "📂 Твои обращения:\n" + "\n".join("#%d · %s · %s" % (
            r["id"], time.strftime("%d.%m %H:%M", time.localtime(r["ts"])), r["text"][:50]) for r in rows))
    if c.startswith("/ticket"):
        body = raw[7:].strip()
        if not body:
            return say(me_, uid, "Напиши так: /ticket опиши проблему 📝")
        tid = q("INSERT INTO tickets(uid,text,ts) VALUES(?,?,?)", (uid, body[:500], now()), w=True)
        return say(me_, uid, "📨 Обращение #%d создано. Мы ответим здесь же. Список: /tickets" % tid)
    for keys, ans in SUP:
        if any(k in c for k in keys):
            return say(me_, uid, ans)
    tid = q("INSERT INTO tickets(uid,text,ts) VALUES(?,?,?)", (uid, raw[:500], now()), w=True)
    say(me_, uid, secrets.choice([
        "📨 Обращение #%d принято. Опиши подробнее, что случилось — или выбери тему: /help",
        "📝 Записала (#%d). Уточни, пожалуйста: что делал и что пошло не так? Быстрые ответы — /help",
        "🛟 Обращение #%d создано. Пока ищу решение, посмотри /help — вдруг ответ уже там."]) % tid)


def bot_reply(b, u, t, gift):
    t = (t or "").strip()
    n = b["nick"].lower()
    if b["owner"] is None:  # системные боты (регистр ника не важен)
        if n == "nova_nft_bot":
            return nft_bot(b, u, t)
        if n == "galochka_bot":
            return galochka_bot(b, u, t)
        if n == "ratra_bot":
            return ratra_bot(b, u, t)
        if n == "spambot_info":
            return spam_bot(b, u, t)
        if n == "novasupport":
            return support_bot(b, u, t, gift)
    r = q("SELECT reply FROM bcmd WHERE bot=? AND ulow(trig)=ulow(?)", (b["id"], t), one=True)
    say(b["id"], u["id"], r["reply"] if r else (b["bio"] or "Привет! Я бот.") if t == "/start"
        else "Я не знаю такой команды 🤖")


# ───────── ФОНОВЫЙ ПОМОЩНИК ─────────
def janitor():
    while True:
        time.sleep(10)
        try:
            if not admin_ids():  # автопроверка апелляций — только если нет человека-модератора
                for r in q("SELECT id FROM users WHERE frozen=1 AND appeal_ts>0 AND appeal_ts+?<=?", (APPEAL_SEC, now())):
                    unfreeze_user(r["id"])
            for r in q("SELECT id FROM users WHERE frozen=2 AND del_at>0 AND del_at<=?", (now(),)):
                purge_user(r["id"])
        except Exception:
            pass


# ───────── ЧАТЫ, ГРУППЫ, КАНАЛЫ ─────────
_TY = {}  # (кто, кому) -> время последнего «печатает…»


@app.post("/api/typing")
@need_login
def typing():
    t = (request.json or {}).get("to")
    if isinstance(t, int) and t != 0:
        _TY[(me()["id"], t)] = now()
    return jsonify(ok=True)


def pkey(uid, pid):  # ключ закреплённого сообщения чата
    return "g%d" % -pid if pid < 0 else "d%d_%d" % (min(uid, pid), max(uid, pid))


@app.get("/api/chats")
@need_login
def chats():
    i, out, res = me()["id"], {}, []
    for m in q("""SELECT id,frm,uid,gid,text,gift,sticker,ts,(img!='') hi,fwd FROM msgs WHERE id IN (
        SELECT max(id) FROM msgs WHERE gid IS NULL AND (frm=:u OR uid=:u) GROUP BY CASE WHEN frm=:u THEN uid ELSE frm END
        UNION ALL SELECT max(id) FROM msgs WHERE gid IN (SELECT g FROM members WHERE uid=:u) GROUP BY gid)""", {"u": i}):
        out[-m["gid"] if m["gid"] else (m["uid"] if m["frm"] == i else m["frm"])] = m
    for r in q("SELECT g FROM members WHERE uid=?", (i,)):
        out.setdefault(-r["g"], None)
    for r in q("SELECT b FROM follows WHERE a=?", (i,)):
        out.setdefault(r["b"], None)
    pins = {r["peer"] for r in q("SELECT peer FROM pins WHERE uid=?", (i,))}
    mutes = {r["peer"] for r in q("SELECT peer FROM mutes WHERE uid=?", (i,))}
    arc = {r["peer"] for r in q("SELECT peer FROM arch WHERE uid=?", (i,))}
    cl = {r["peer"]: r["lid"] for r in q("SELECT peer,lid FROM clr WHERE uid=?", (i,))}
    rd = {r["uid"]: r["lid"] for r in q("SELECT uid,lid FROM rdst WHERE peer=?", (i,))}
    for p_ in pins | arc:
        out.setdefault(p_, None)
    out.setdefault(i, None)  # «Избранное»
    un = {r["frm"]: r["c"] for r in q(
        "SELECT m.frm, COUNT(*) c FROM msgs m WHERE m.uid=? AND m.gid IS NULL AND m.frm!=m.uid AND "
        "m.id>COALESCE((SELECT lid FROM rdst WHERE uid=? AND peer=m.frm),0) GROUP BY m.frm", (i, i))}
    for pid, m in out.items():
        if m and m["id"] <= cl.get(pid, 0):
            m = None  # история очищена
        if pid < 0:
            x = q("SELECT * FROM grps WHERE id=?", (-pid,), one=True)
            p = gpub(x) if x else None
        else:
            x = q("SELECT * FROM users WHERE id=?", (pid,), one=True)
            p = pub(x, pid == i) if x else None
        if not p:
            continue
        hide = (p.get("gone") or p.get("frozen")) and pid != i
        base = dict(p, ts=0, un=0, pin=pid in pins, mute=pid in mutes, arch=pid in arc, mine=False, rd=False)
        if not m:
            res.append(dict(base, last="❄️ Недоступно" if hide else "Нет сообщений"))
            continue
        if m["gift"] in GMAP:
            txt = "🎁 " + GMAP[m["gift"]]["n"]
        elif m["sticker"]:
            txt = "Стикер " + m["sticker"]
        elif m["hi"]:
            txt = "📷 " + (m["text"] or "Фото")
        else:
            txt = ("↪ " if m["fwd"] else "") + m["text"]
        if hide:
            txt = "❄️ Недоступно"
        res.append(dict(base, last=("Вы: " if m["frm"] == i else "") + txt, ts=m["ts"], un=un.get(pid, 0),
                        mine=m["frm"] == i and pid != i and pid > 0, rd=pid > 0 and m["id"] <= rd.get(pid, 0)))
    res.sort(key=lambda x: (x["id"] != i, not x["pin"], -x["ts"]))
    return jsonify(chats=res)


@app.post("/api/pin")
@need_login
def pin():
    d, u = request.json or {}, me()
    t = d.get("id")
    if not isinstance(t, int) or t == 0:
        return err("Чат не найден")
    if d.get("off"):
        q("DELETE FROM pins WHERE uid=? AND peer=?", (u["id"], t), w=True)
    else:
        if not q("SELECT 1 FROM %s WHERE id=?" % ("grps" if t < 0 else "users"), (abs(t),), one=True):
            return err("Чат не найден")
        q("INSERT OR IGNORE INTO pins(uid,peer) VALUES(?,?)", (u["id"], t), w=True)
    return jsonify(ok=True)


@app.post("/api/mute")
@need_login
def mute():
    d, u = request.json or {}, me()
    t = d.get("id")
    if not isinstance(t, int) or t == 0:
        return err("Чат не найден")
    if d.get("off"):
        q("DELETE FROM mutes WHERE uid=? AND peer=?", (u["id"], t), w=True)
    else:
        q("INSERT OR IGNORE INTO mutes(uid,peer) VALUES(?,?)", (u["id"], t), w=True)
    return jsonify(ok=True)


@app.post("/api/archive")
@need_login
def archive():  # архив чатов, как в Telegram
    d, u = request.json or {}, me()
    t = d.get("id")
    if not isinstance(t, int) or t == 0:
        return err("Чат не найден")
    if d.get("off"):
        q("DELETE FROM arch WHERE uid=? AND peer=?", (u["id"], t), w=True)
    else:
        q("INSERT OR IGNORE INTO arch(uid,peer) VALUES(?,?)", (u["id"], t), w=True)
    return jsonify(ok=True)


@app.post("/api/chat/clear")
@need_login
def chat_clear():  # очистить историю (только у тебя)
    d, u = request.json or {}, me()
    t = d.get("id")
    if not isinstance(t, int) or t == 0:
        return err("Чат не найден")
    if t < 0:
        if not ismem(-t, u["id"]):
            return err("Нет доступа", 403)
        r = q("SELECT MAX(id) m FROM msgs WHERE gid=?", (-t,), one=True)
    else:
        r = q("SELECT MAX(id) m FROM msgs WHERE gid IS NULL AND ((frm=? AND uid=?) OR (frm=? AND uid=?))",
              (u["id"], t, t, u["id"]), one=True)
    q("INSERT OR REPLACE INTO clr(uid,peer,lid) VALUES(?,?,?)", (u["id"], t, (r["m"] or 0) if r else 0), w=True)
    return jsonify(ok=True)


@app.post("/api/msg/pin")
@need_login
def msg_pin():  # закрепить сообщение в чате (в группах — админы)
    d, u = request.json or {}, me()
    m = q("SELECT id,frm,uid,gid FROM msgs WHERE id=?", (d.get("id"),), one=True)
    if not m:
        return err("Сообщение не найдено")
    if m["gid"]:
        x = grp(m["gid"])
        if not x or x["frozen"] or grole(x, u["id"]) not in ("owner", "admin"):
            return err("Закреплять могут только админы", 403)
        k = "g%d" % m["gid"]
    else:
        if u["id"] not in (m["frm"], m["uid"]):
            return err("Нет доступа", 403)
        k = "d%d_%d" % (min(m["frm"], m["uid"]), max(m["frm"], m["uid"]))
    if d.get("off"):
        q("DELETE FROM pmsg WHERE k=?", (k,), w=True)
    else:
        q("INSERT OR REPLACE INTO pmsg(k,mid) VALUES(?,?)", (k, m["id"]), w=True)
    return jsonify(ok=True)


@app.post("/api/block")
@need_login
def block():
    d, u = request.json or {}, me()
    t = d.get("id")
    x = q("SELECT is_bot FROM users WHERE id=?", (t,), one=True) if isinstance(t, int) else None
    if not x or t == u["id"]:
        return err("Пользователь не найден")
    if x["is_bot"] and not q("SELECT 1 FROM users WHERE id=? AND owner IS NOT NULL", (t,), one=True):
        return err("Системных ботов блокировать нельзя")
    if d.get("off"):
        q("DELETE FROM blocks WHERE a=? AND b=?", (u["id"], t), w=True)
    else:
        q("INSERT OR IGNORE INTO blocks(a,b) VALUES(?,?)", (u["id"], t), w=True)
    return jsonify(ok=True)


@app.get("/api/blocks")
@need_login
def blocks_list():
    return jsonify(items=[pub(r) for r in q("SELECT u.* FROM blocks b JOIN users u ON u.id=b.b WHERE b.a=?",
                                            (me()["id"],))])


@app.get("/api/users")
@need_login
def users():
    s = (request.args.get("q") or "").strip().lstrip("@")
    if not s:
        return jsonify(users=[], groups=[])
    k = s.casefold()
    like = "%" + re.sub(r"([\\%_])", r"\\\1", k) + "%"
    rows = q(r"""SELECT * FROM users WHERE id!=? AND frozen=0 AND (ulow(nick) LIKE ? ESCAPE '\' OR ulow(name) LIKE ? ESCAPE '\'
        OR id IN (SELECT uid FROM unames WHERE ulow(name) LIKE ? ESCAPE '\'))
        ORDER BY (ulow(nick)=?) DESC, (ulow(name) LIKE ? ESCAPE '\') DESC, is_bot, name LIMIT 30""",
             (me()["id"], like, like, like, k, like))
    gs = q(r"SELECT * FROM grps WHERE frozen=0 AND (ulow(title) LIKE ? ESCAPE '\' OR ulow(COALESCE(uname,'')) LIKE ? ESCAPE '\') LIMIT 10",
           (like, like))
    return jsonify(users=[pub(r) for r in rows], groups=[gpub(x) for x in gs])


@app.get("/api/user/<int:uid>")
@need_login
def user_page(uid):
    u, x = me(), q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    if not x:
        return err("Нет такого пользователя", 404)
    c = lambda sql: q(sql, (uid,), one=True)["c"]
    d = pub(x, uid == u["id"])
    masked = d["gone"] and uid != u["id"]
    d.update(created=x["created"], self=uid == u["id"], bgn=None if masked else (nft_of(x, "nft_bg") or d["nft"]),
             nfl=c("SELECT COUNT(*) c FROM follows WHERE b=?"), nfg=c("SELECT COUNT(*) c FROM follows WHERE a=?"),
             gifts=c("SELECT COUNT(*) c FROM msgs WHERE uid=? AND gift IS NOT NULL"),
             bday="" if masked else x["bday"], score=0 if masked else x["score"],
             blk=q("SELECT 1 FROM blocks WHERE a=? AND b=?", (u["id"], uid), one=True) is not None,
             me_follow=q("SELECT 1 FROM follows WHERE a=? AND b=?", (u["id"], uid), one=True) is not None,
             fl=[pub(r) for r in q("SELECT u.* FROM follows f JOIN users u ON u.id=f.a WHERE f.b=? "
                                   "ORDER BY f.ts DESC LIMIT 50", (uid,))],
             fg=[pub(r) for r in q("SELECT u.* FROM follows f JOIN users u ON u.id=f.b WHERE f.a=? "
                                   "ORDER BY f.ts DESC LIMIT 50", (uid,))])
    return jsonify(d)


@app.post("/api/follow")
@need_login
def follow():
    d, u = request.json or {}, me()
    t = d.get("id")
    if not isinstance(t, int) or t == u["id"] or not q("SELECT 1 FROM users WHERE id=?", (t,), one=True):
        return err("Аккаунт не найден")
    if d.get("off"):
        q("DELETE FROM follows WHERE a=? AND b=?", (u["id"], t), w=True)
    else:
        q("INSERT OR IGNORE INTO follows(a,b,ts) VALUES(?,?,?)", (u["id"], t, now()), w=True)
    return jsonify(ok=True)


@app.post("/api/msg/delete")
@need_login
def msg_delete():  # свои сообщения; в группах/каналах — любые, если ты админ или владелец
    i = me()["id"]
    q("DELETE FROM msgs WHERE id=? AND gift IS NULL AND (frm=? OR gid IN ("
      "SELECT m.g FROM members m JOIN grps g ON g.id=m.g WHERE m.uid=? AND (m.admin=1 OR g.owner=?)))",
      ((request.json or {}).get("id"), i, i, i), w=True)
    return jsonify(ok=True)


@app.post("/api/msg/edit")
@need_login
def msg_edit():
    d = request.json or {}
    t = (d.get("text") or "").strip()[:2000]
    if not t:
        return err("Пустое сообщение")
    n = q("UPDATE msgs SET text=?, edt=? WHERE id=? AND frm=? AND gift IS NULL AND sticker IS NULL",
          (t, now(), d.get("id"), me()["id"]), w=True)
    return jsonify(ok=True) if n else err("Нельзя изменить это сообщение")


@app.post("/api/react")
@need_login
def react():
    d, u = request.json or {}, me()
    e = d.get("e")
    m = q("SELECT id,frm,uid,gid FROM msgs WHERE id=?", (d.get("id"),), one=True)
    if e not in REACTS or not m:
        return err("Нельзя поставить реакцию")
    ok = ismem(m["gid"], u["id"]) if m["gid"] else u["id"] in (m["frm"], m["uid"])
    if not ok:
        return err("Нет доступа", 403)
    cur = q("SELECT e FROM react WHERE mid=? AND uid=?", (m["id"], u["id"]), one=True)
    if cur and cur["e"] == e:
        q("DELETE FROM react WHERE mid=? AND uid=?", (m["id"], u["id"]), w=True)
    else:
        q("INSERT OR REPLACE INTO react(mid,uid,e,ts) VALUES(?,?,?,?)", (m["id"], u["id"], e, now()), w=True)
    return jsonify(ok=True)


def rx_of(ids, uid):
    out = {}
    if not ids:
        return out
    for r in q("SELECT mid,e,COUNT(*) c,SUM(uid=?) me FROM react WHERE mid IN (%s) GROUP BY mid,e ORDER BY MIN(ts)" %
               ",".join("?" * len(ids)), [uid] + list(ids)):
        out.setdefault(r["mid"], []).append({"e": r["e"], "c": r["c"], "me": bool(r["me"])})
    return out


def rq_of(m):
    if not m["rep"] or m["rn"] is None:
        return None
    t = m["rt"] or ("📷 Фото" if m["rhi"] else (
        "Стикер " + m["rs"] if m["rs"] else ("🎁 " + GMAP[m["rg"]]["n"] if m["rg"] in GMAP else "")))
    return {"n": m["rn"], "t": t[:80]}


@app.get("/api/messages/<int(signed=True):pid>")
@need_login
def messages(pid):
    u, after, tn = me(), int(request.args.get("after", 0)), now()
    try:
        since = float(request.args.get("since", 0) or 0)
    except ValueError:
        since = 0
    cr = q("SELECT lid FROM clr WHERE uid=? AND peer=?", (u["id"], pid), one=True)
    after = max(after, cr["lid"] if cr else 0)  # очищенная история не показывается
    base = ("SELECT m.id, m.frm, m.uid, m.gid, m.text, m.gift, m.sticker, m.rep, m.edt, m.ts, (m.img!='') hi, m.fwd, "
            "CASE WHEN u.frozen THEN '" + FROZEN_NAME + "' ELSE u.name END sn, u.frozen ufz, (u.avatar!='') hav, u.avts, "
            "r.text rt, r.sticker rs, r.gift rg, (r.img!='') rhi, "
            "CASE WHEN ru.frozen THEN '" + FROZEN_NAME + "' ELSE ru.name END rn FROM msgs m "
            "JOIN users u ON u.id=m.frm LEFT JOIN msgs r ON r.id=m.rep LEFT JOIN users ru ON ru.id=r.frm ")
    pr, edits, wids, ty = 0, [], [], []
    if pid < 0:
        x = q("SELECT * FROM grps WHERE id=?", (-pid,), one=True)
        if not x:
            return err("Нет такой группы", 404)
        role = grole(x, u["id"])
        frz = bool(x["frozen"])
        mem = role is not None and not frz
        rows = q(base + "WHERE m.gid=? AND m.id>? ORDER BY m.id", (-pid, after)) if mem else []
        if mem and since:
            edits = q("SELECT id,text FROM msgs WHERE gid=? AND edt>?", (-pid, since))
        if mem:
            wids = [r["id"] for r in q("SELECT id FROM msgs WHERE gid=? ORDER BY id DESC LIMIT 80", (-pid,))]
            for (f, t), ts in list(_TY.items()):
                if t == pid and f != u["id"] and tn - ts < 4:
                    r = q("SELECT name FROM users WHERE id=? AND frozen=0", (f,), one=True)
                    if r:
                        ty.append(r["name"])
        peer = gpub(x)
        peer.update(joined=role is not None, role="" if frz else (role or ""),
                    can_post=bool(mem and (x["kind"] == "group" or role in ("owner", "admin"))))
    else:
        p = q("SELECT * FROM users WHERE id=?", (pid,), one=True)
        if not p:
            return err("Нет такого пользователя", 404)
        peer = pub(p, pid == u["id"])
        peer["blk"] = q("SELECT 1 FROM blocks WHERE a=? AND b=?", (u["id"], pid), one=True) is not None
        if p["is_bot"]:
            peer["cmds"] = BC.get(p["nick"].lower()) if p["owner"] is None else (
                ["/start"] + [c["trig"] for c in q("SELECT trig FROM bcmd WHERE bot=? LIMIT 8", (pid,))])
        where = "((frm=? AND uid=?) OR (frm=? AND uid=?))"
        rows = q(base + "WHERE m.id>? AND m.gid IS NULL AND ((m.frm=? AND m.uid=?) OR (m.frm=? AND m.uid=?)) "
                        "ORDER BY m.id", (after, u["id"], pid, pid, u["id"]))
        if since:
            edits = q("SELECT id,text FROM msgs WHERE gid IS NULL AND " + where + " AND edt>?",
                      (u["id"], pid, pid, u["id"], since))
        wids = [r["id"] for r in q("SELECT id FROM msgs WHERE gid IS NULL AND " + where + " ORDER BY id DESC LIMIT 80",
                                   (u["id"], pid, pid, u["id"]))]
        if pid != u["id"]:  # отметка «прочитано» + «печатает…»
            last = q("SELECT MAX(id) m FROM msgs WHERE frm=? AND uid=? AND gid IS NULL", (pid, u["id"]), one=True)["m"] or 0
            if last:
                q("INSERT OR IGNORE INTO rdst(uid,peer,lid) VALUES(?,?,0)", (u["id"], pid), w=True)
                q("UPDATE rdst SET lid=? WHERE uid=? AND peer=? AND lid<?", (last, u["id"], pid, last), w=True)
            r = q("SELECT lid FROM rdst WHERE uid=? AND peer=?", (pid, u["id"]), one=True)
            pr = r["lid"] if r else 0
            if tn - _TY.get((pid, u["id"]), 0) < 4:
                ty = [peer["name"]]
    peer["pin"] = q("SELECT 1 FROM pins WHERE uid=? AND peer=?", (u["id"], pid), one=True) is not None
    peer["mute"] = q("SELECT 1 FROM mutes WHERE uid=? AND peer=?", (u["id"], pid), one=True) is not None
    peer["arch"] = q("SELECT 1 FROM arch WHERE uid=? AND peer=?", (u["id"], pid), one=True) is not None
    pm = q("SELECT m.id, m.text, m.sticker, (m.img!='') hi FROM pmsg p JOIN msgs m ON m.id=p.mid WHERE p.k=?",
           (pkey(u["id"], pid),), one=True)
    pinned = None
    if pm and not (pid < 0 and peer.get("frozen")):
        pinned = {"id": pm["id"], "t": (pm["text"] or ("📷 Фото" if pm["hi"] else (pm["sticker"] or "Сообщение")))[:80]}
    return jsonify(peer=peer, now=tn, pr=pr, typing=ty, pinned=pinned,
                   edits=[dict(id=e["id"], text=e["text"]) for e in edits],
                   rx=rx_of(wids, u["id"]), rxfrom=min(wids) if wids else 0,
                   msgs=[dict(id=m["id"], mine=m["frm"] == u["id"], text=m["text"], gift=GMAP.get(m["gift"]),
                              sticker=m["sticker"], who=m["sn"] if pid < 0 else None, wid=m["frm"] if pid < 0 else 0,
                              wav=("/av/%d?v=%d" % (m["frm"], m["avts"]) if m["hav"] and not m["ufz"] else None)
                              if pid < 0 else None, wfz=bool(m["ufz"]) if pid < 0 else False,
                              ts=m["ts"], ed=m["edt"] > 0, rq=rq_of(m), img=bool(m["hi"]), fwd=m["fwd"] or None)
                         for m in rows])


def deliver(u, pid, text="", gift=None, st=None, img="", rp=None, fwd=""):
    """Общая отправка сообщения. Возвращает ответ-ошибку или None, если всё хорошо."""
    if not isinstance(pid, int) or pid == 0:
        return err("Получатель не найден")
    if u["frozen"] == 1 and pid != bot_id("SpamBot_Info"):
        return err("❄️ Аккаунт заморожен: писать можно только @SpamBot_Info")
    if st and st not in STICKERS:
        return err("Нет такого стикера")
    if gift:
        img = ""
    if img and not (isinstance(img, str) and len(img) < 2600000 and re.match(IMG_RE, img)):
        return err("Не удалось отправить картинку (формат или размер)")
    uid = gid = None
    if pid < 0:
        x = q("SELECT * FROM grps WHERE id=?", (-pid,), one=True)
        if not x or not ismem(x["id"], u["id"]):
            return err("Сначала вступи в чат")
        if x["frozen"]:
            return err("❄️ Данный чат недоступен из-за нарушения правил сообщества")
        if x["kind"] == "channel" and not gift and grole(x, u["id"]) not in ("owner", "admin"):
            return err("В канале пишут только админы")
        gid = -pid
    else:
        tu = q("SELECT id, frozen FROM users WHERE id=?", (pid,), one=True)
        if not tu:
            return err("Получатель не найден")
        if tu["frozen"] and pid != u["id"]:
            return err("❄️ Этот аккаунт недоступен")
        if pid != u["id"]:
            if q("SELECT 1 FROM blocks WHERE a=? AND b=?", (pid, u["id"]), one=True):
                return err("🚫 Пользователь ограничил получение сообщений")
            if q("SELECT 1 FROM blocks WHERE a=? AND b=?", (u["id"], pid), one=True):
                return err("🚫 Ты заблокировал этого пользователя — разблокируй его в меню чата")
        uid = pid
        if gift and pid == u["id"]:
            return err("Нельзя подарить подарок самому себе")
    if gift:
        gg = GMAP.get(gift)
        if not gg:
            return err("Нет такого подарка")
        if not spend(u["id"], gg["p"], "gift"):
            return err("Не хватает звёзд ★")
    elif not text and not st and not img:
        return err("Пустое сообщение")
    if not (isinstance(rp, int) and q("SELECT 1 FROM msgs WHERE id=?", (rp,), one=True)):
        rp = None
    q("INSERT INTO msgs(frm,uid,gid,text,gift,sticker,rep,ts,img,fwd) VALUES(?,?,?,?,?,?,?,?,?,?)",
      (u["id"], uid, gid, text, gift, st, rp, now(), img, fwd[:60]), w=True)
    _TY.pop((u["id"], pid), None)
    if uid and uid != u["id"]:
        b = q("SELECT * FROM users WHERE id=?", (uid,), one=True)
        if b["is_bot"]:
            bot_reply(b, me(), text, gift)
    return None


@app.post("/api/send")
@need_login
def send():
    d, u = request.json or {}, me()
    r = deliver(u, d.get("to"), (d.get("text") or "").strip()[:2000], d.get("gift"), d.get("sticker"),
                d.get("img") or "", d.get("reply"))
    return r or jsonify(ok=True)


@app.post("/api/forward")
@need_login
def forward():
    d, u = request.json or {}, me()
    m = q("SELECT m.*, CASE WHEN s.frozen THEN '" + FROZEN_NAME + "' ELSE s.name END sn FROM msgs m "
          "JOIN users s ON s.id=m.frm WHERE m.id=?", (d.get("id"),), one=True)
    if not m or m["gift"]:
        return err("Это сообщение нельзя переслать")
    ok = ismem(m["gid"], u["id"]) if m["gid"] else u["id"] in (m["frm"], m["uid"])
    if not ok:
        return err("Нет доступа", 403)
    r = deliver(u, d.get("to"), m["text"], None, m["sticker"], m["img"], None, m["fwd"] or m["sn"])
    return r or jsonify(ok=True)


# ── группы и каналы ──
@app.post("/api/group/create")
@need_login
def group_create():
    d, u = request.json or {}, me()
    title, kind = (d.get("title") or "").strip()[:40], d.get("kind")
    if kind not in ("group", "channel") or len(title) < 2:
        return err("Название минимум 2 символа")
    gid = q("INSERT INTO grps(kind,title,owner) VALUES(?,?,?)", (kind, title, u["id"]), w=True)
    q("INSERT INTO members(g,uid) VALUES(?,?)", (gid, u["id"]), w=True)
    return jsonify(id=-gid)


@app.post("/api/group/join")
@need_login
def group_join():
    gid = (request.json or {}).get("id")
    x = grp(gid)
    if not x:
        return err("Нет такой группы")
    if x["frozen"]:
        return err("❄️ Данный чат недоступен из-за нарушения правил сообщества")
    q("INSERT OR IGNORE INTO members(g,uid) VALUES(?,?)", (gid, me()["id"]), w=True)
    return jsonify(ok=True)


@app.post("/api/group/leave")
@need_login
def group_leave():
    u, x = me(), grp((request.json or {}).get("id"))
    if x and x["owner"] == u["id"]:
        return err("Владелец не может выйти: передай владение другому участнику или удали группу")
    q("DELETE FROM members WHERE g=? AND uid=?", ((request.json or {}).get("id"), u["id"]), w=True)
    return jsonify(ok=True)


@app.get("/api/group/info")
@need_login
def group_info():
    u = me()
    try:
        gid = int(request.args.get("id", 0))
    except ValueError:
        gid = 0
    x = grp(gid)
    if not x:
        return err("Нет такой группы", 404)
    if x["frozen"]:
        return jsonify(info=gpub(x), role="", members=[], gifts=[])
    role = grole(x, u["id"])
    ms = []
    if role:
        for r in q("SELECT u.*, m.admin AS adm FROM members m JOIN users u ON u.id=m.uid WHERE m.g=? "
                   "ORDER BY (u.id=?) DESC, m.admin DESC, u.name LIMIT 300", (gid, x["owner"])):
            d = pub(r)
            d["role"] = "owner" if r["id"] == x["owner"] else ("admin" if r["adm"] else "member")
            ms.append(d)
    gifts = [dict(g=GMAP[r["gift"]], frm=r["name"]) for r in q(
        "SELECT m.gift, CASE WHEN u.frozen THEN '" + FROZEN_NAME + "' ELSE u.name END name FROM msgs m "
        "JOIN users u ON u.id=m.frm WHERE m.gid=? AND m.gift IS NOT NULL "
        "ORDER BY m.id DESC LIMIT 100", (gid,)) if r["gift"] in GMAP]
    return jsonify(info=gpub(x), role=role or "", members=ms, gifts=gifts)


@app.post("/api/group/edit")
@need_login
def group_edit():
    d, u = request.json or {}, me()
    x = grp(d.get("id"))
    if not x:
        return err("Нет такой группы")
    if grole(x, u["id"]) not in ("owner", "admin"):
        return err("Недостаточно прав", 403)
    title = (d.get("title", x["title"]) or "").strip()[:40]
    if len(title) < 2:
        return err("Название минимум 2 символа")
    q("UPDATE grps SET title=?, bio=? WHERE id=?", (title, (d.get("desc", x["bio"]) or "").strip()[:200], x["id"]), w=True)
    return jsonify(ok=True)


@app.post("/api/group/uname")
@need_login
def group_uname():
    d, u = request.json or {}, me()
    x = grp(d.get("id"))
    if not x or x["owner"] != u["id"]:
        return err("Юзернейм меняет только владелец", 403)
    n = (d.get("name") or "").strip().lstrip("@").lower()
    if n:
        if not valid_nick(n):
            return err("Юзернейм: 3–20 символов, буквы/цифры/_")
        if n != (x["uname"] or "").lower() and not nick_free(n):
            return err("Этот юзернейм занят — его можно взять только когда он освободится")
    q("UPDATE grps SET uname=? WHERE id=?", (n or None, x["id"]), w=True)
    return jsonify(ok=True)


@app.post("/api/group/nft")
@need_login
def group_nft():
    d, u = request.json or {}, me()
    x = grp(d.get("id"))
    if not x or x["owner"] != u["id"]:
        return err("NFT вешает только владелец", 403)
    i = d.get("nft") or 0
    if i and not q("SELECT 1 FROM nftg WHERE id=? AND uid=?", (i, u["id"]), one=True):
        return err("Это не твой NFT")
    q("UPDATE grps SET nft=? WHERE id=?", (i, x["id"]), w=True)
    return jsonify(ok=True)


@app.post("/api/group/admin")
@need_login
def group_admin():
    d, u = request.json or {}, me()
    x, t = grp(d.get("id")), d.get("uid")
    if not x or x["owner"] != u["id"]:
        return err("Админов назначает только владелец", 403)
    if not isinstance(t, int) or t == x["owner"] or not ismem(x["id"], t):
        return err("Пользователь не в группе")
    q("UPDATE members SET admin=? WHERE g=? AND uid=?", (1 if d.get("on") else 0, x["id"], t), w=True)
    if d.get("on"):
        notify(t, "🛡 Тебя назначили админом «%s»." % x["title"])
    return jsonify(ok=True)


@app.post("/api/group/transfer")
@need_login
def group_transfer():
    d, u = request.json or {}, me()
    x, t = grp(d.get("id")), d.get("uid")
    if not x or x["owner"] != u["id"]:
        return err("Передать владение может только владелец", 403)
    if not isinstance(t, int) or t == u["id"] or not ismem(x["id"], t):
        return err("Пользователь не в группе")
    q("UPDATE grps SET owner=?, nft=0 WHERE id=?", (t, x["id"]), w=True)
    q("UPDATE members SET admin=0 WHERE g=? AND uid=?", (x["id"], t), w=True)
    q("UPDATE members SET admin=1 WHERE g=? AND uid=?", (x["id"], u["id"]), w=True)
    notify(t, "👑 Тебе передали владение «%s». Теперь ты полный хозяин." % x["title"])
    return jsonify(ok=True)


@app.post("/api/group/kick")
@need_login
def group_kick():
    d, u = request.json or {}, me()
    x, t = grp(d.get("id")), d.get("uid")
    if not x:
        return err("Нет такой группы")
    r, tr = grole(x, u["id"]), grole(x, t) if isinstance(t, int) else None
    if r not in ("owner", "admin") or not tr or tr == "owner" or t == u["id"] or (r == "admin" and tr != "member"):
        return err("Недостаточно прав", 403)
    q("DELETE FROM members WHERE g=? AND uid=?", (x["id"], t), w=True)
    return jsonify(ok=True)


@app.post("/api/group/delete")
@need_login
def group_delete():
    x, u = grp((request.json or {}).get("id")), me()
    if not x or x["owner"] != u["id"]:
        return err("Удалить может только владелец", 403)
    for t in ("pins", "mutes", "arch", "clr"):
        q("DELETE FROM %s WHERE peer=?" % t, (-x["id"],), w=True)
    q("DELETE FROM grps WHERE id=?", (x["id"],), w=True)
    return jsonify(ok=True)


@app.get("/api/mygifts")
@need_login
def mygifts():
    rows = q("SELECT m.gift, CASE WHEN u.frozen THEN '" + FROZEN_NAME + "' ELSE u.name END name FROM msgs m "
             "JOIN users u ON u.id=m.frm WHERE m.uid=? AND m.gift IS NOT NULL "
             "ORDER BY m.id DESC", (me()["id"],))
    return jsonify(items=[dict(g=GMAP[r["gift"]], frm=r["name"]) for r in rows if r["gift"] in GMAP])


# ───────── ИНТЕРФЕЙС ─────────
@app.get("/")
def index():
    return PAGE


PAGE = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0f1a"><title>Nova</title>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Unbounded:wght@500;700&display=swap" rel="stylesheet">
<script src="https://accounts.google.com/gsi/client" async defer></script>
<style>
:root{--bg:#0b0f1a;--bg2:#0f1526;--card:#171f33;--card2:#222d47;--tx:#eef2fb;--mut:#8a96b3;--ac:#5b8cff;--ac2:#9b5cff;--bad:#ff5d73;--ok:#34d399;--g:linear-gradient(135deg,#5b8cff,#9b5cff);--bin:#1b2540;--bout:linear-gradient(135deg,#4f86ff,#7a56ff)}
body.light{--bg:#eef2fa;--bg2:#e4eaf6;--card:#fff;--card2:#e8edf7;--tx:#141a2b;--mut:#6b7794;--bin:#fff}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%;overflow:hidden}
body{background:var(--bg);color:var(--tx);font-family:Manrope,system-ui,sans-serif;font-weight:500}
#app{position:fixed;inset:0;max-width:520px;margin:auto;display:flex;flex-direction:column;overflow:hidden;background:var(--bg)}
h1,h2{font-family:Unbounded,Manrope,sans-serif;margin:0}
svg{flex:none}
.blob{position:absolute;border-radius:50%;filter:blur(70px);opacity:.5;animation:fl 9s ease-in-out infinite alternate}
@keyframes fl{to{transform:translate(40px,-50px) scale(1.2)}}
@keyframes up{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
@keyframes rot{to{transform:rotate(360deg)}}
.center{position:relative;z-index:1;flex:1;display:flex;flex-direction:column;justify-content:center;padding:26px;gap:13px;overflow:auto;animation:up .45s}
.logo{width:104px;height:104px;margin:0 auto;border-radius:34px;background:var(--g);display:flex;align-items:center;justify-content:center;color:#fff;box-shadow:0 20px 60px #5b8cff66;transform:rotate(-6deg);position:relative}
.logo:after{content:"";position:absolute;inset:-10px;border-radius:42px;border:2px solid #5b8cff55;animation:lp 3s ease-in-out infinite}
@keyframes lp{50%{transform:scale(1.1);opacity:.2}}
.t1{text-align:center;font-size:36px;margin-top:12px;background:linear-gradient(135deg,#7fb0ff,#c08cff 60%,#ff8ad8);-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{text-align:center;color:var(--mut);margin:0 0 6px;line-height:1.5}
.glass{background:#ffffff0f;backdrop-filter:blur(18px);border:1px solid #ffffff1c;border-radius:28px;padding:20px;display:flex;flex-direction:column;gap:11px}
body.light .glass{background:#ffffffb8;border-color:#fff}
.steps{display:flex;gap:8px;justify-content:center}.steps i{width:34px;height:6px;border-radius:3px;background:var(--card2);transition:.3s}.steps i.on{background:var(--g);width:46px}
.fbub{position:absolute;padding:9px 15px;border-radius:18px;font-size:14px;font-weight:700;color:#fff;opacity:.9;animation:fb 7s ease-in-out infinite alternate;box-shadow:0 8px 24px #0004;z-index:0}
.fbub.o{background:var(--bout)}.fbub.i{background:var(--card2)}
@keyframes fb{to{transform:translateY(-24px) rotate(2deg)}}
.chip{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;border-radius:16px;background:var(--card);font-size:13px;font-weight:700;color:var(--mut)}
.btn{border:0;border-radius:16px;padding:16px;font:700 16px Manrope,sans-serif;color:#fff;background:var(--g);width:100%;cursor:pointer;box-shadow:0 10px 28px #5b8cff44;transition:.15s}
.btn:active{transform:scale(.97)}.btn.gl{background:var(--card);color:var(--tx);box-shadow:none;border:1px solid #8a96b333}
.btn.bad{background:#ff5d7322;color:var(--bad);box-shadow:none}.btn.sm{width:auto;padding:11px 20px;font-size:14px}
.lnk{background:none;border:0;color:var(--ac);font:700 14px Manrope,sans-serif;cursor:pointer;padding:4px}
input,textarea{width:100%;padding:16px;border-radius:16px;border:1.5px solid transparent;background:var(--card);color:var(--tx);font:500 16px Manrope,sans-serif;outline:0;transition:.2s}
input:focus,textarea:focus{border-color:var(--ac);box-shadow:0 0 0 4px #5b8cff22}
.iw{position:relative}.iw input{padding-right:52px}.eye{position:absolute;right:8px;top:50%;transform:translateY(-50%);border:0;background:none;color:var(--mut);padding:8px;cursor:pointer}
.sbar{height:5px;border-radius:3px;background:var(--card2);overflow:hidden;margin-top:-4px}.sbar i{display:block;height:100%;width:0;transition:.3s}
.hint{font-size:12.5px;min-height:16px;color:var(--mut);margin:-4px 4px 0;font-weight:600}
.err{color:var(--bad);text-align:center;min-height:18px;font-size:14px;font-weight:600}
.back,.ib{border:0;background:var(--card);color:var(--tx);width:42px;height:42px;border-radius:14px;display:flex;align-items:center;justify-content:center;cursor:pointer;flex:none}
.ib.go{background:var(--g);color:#fff}.ib.gl{background:#ffffff26;color:#fff;backdrop-filter:blur(8px)}
header{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:12px;padding:16px 18px 12px;background:var(--bg)}
header.ch{padding:10px 12px;gap:8px;border-bottom:1px solid #8a96b31a;background:linear-gradient(180deg,var(--bg2),var(--bg))}
header h2{font-size:21px;flex:1}.coins{background:var(--card);padding:8px 14px;border-radius:20px;font-size:14px;font-weight:700}
.view{flex:1;overflow:auto;animation:up .3s}.pad{padding:6px 18px 18px}
.ava{border-radius:50%;flex:none;overflow:hidden;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800}
.ava img{width:100%;height:100%;object-fit:cover}
.avw{position:relative;display:inline-flex;flex:none}
.od{position:absolute;right:0;bottom:0;width:15px;height:15px;border-radius:50%;background:var(--ok);border:3px solid var(--bg);box-shadow:0 0 8px var(--ok)}
.row{display:flex;align-items:center;gap:14px;padding:11px 18px;cursor:pointer}.row:active{background:var(--card)}
.row .t{flex:1;min-width:0}.row b{display:block;font-weight:700}.row small{color:var(--mut);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}
.row small.on{color:var(--ac);font-weight:700}
.row .rt{display:flex;flex-direction:column;align-items:flex-end;gap:6px;margin-top:2px;flex:none}
.row .tm{color:var(--mut);font-size:12px}
.ub{min-width:22px;height:22px;padding:0 6px;border-radius:11px;background:var(--g);color:#fff;font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center}
.ub.mu{background:var(--card2);color:var(--mut)}
.tabs{display:flex;gap:8px;padding:0 18px 8px;overflow:auto}.tabs::-webkit-scrollbar{display:none}
.tabs button{flex:none;border:0;border-radius:16px;padding:8px 16px;background:var(--card);color:var(--mut);font:700 13px Manrope,sans-serif;cursor:pointer}
.tabs button.on{background:var(--g);color:#fff}
nav{display:flex;gap:4px;margin:6px 12px max(12px,env(safe-area-inset-bottom));padding:6px;background:var(--card);border-radius:26px;box-shadow:0 10px 36px #0006;flex:none}
nav a{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;padding:9px 0 7px;border-radius:20px;color:var(--mut);font-size:11px;font-weight:700;cursor:pointer;transition:.25s}
nav a.on{background:var(--g);color:#fff;box-shadow:0 6px 18px #5b8cff55}
/* ── сообщения ── */
.msgs{flex:1;overflow:auto;padding:10px 10px 12px;display:flex;flex-direction:column;background:radial-gradient(circle at 10% 0,#5b8cff22,transparent 55%),radial-gradient(circle at 95% 100%,#9b5cff22,transparent 55%),var(--bg2)}
.msgs.cb{background:var(--cbg)!important;background-size:cover!important;background-position:center!important}
.mr{display:flex;align-items:flex-end;gap:6px;margin-top:7px;animation:up .2s}.mr.cp{margin-top:2px}.mr.me{justify-content:flex-end}
.mr.hl .m{animation:hlp 1.4s ease-out}
@keyframes hlp{0%,60%{box-shadow:0 0 0 4px var(--ac),0 0 22px var(--ac)}100%{box-shadow:0 1px 3px #0003}}
.avs{width:30px;flex:none;display:flex}
.m{position:relative;max-width:80%;min-width:56px;padding:7px 11px 6px 12px;border-radius:19px;word-wrap:break-word;overflow-wrap:anywhere;white-space:pre-wrap;cursor:pointer;box-shadow:0 1px 3px #0003;line-height:1.38}
.m.in{background:var(--bin);border-bottom-left-radius:6px}.m.in.cp{border-top-left-radius:6px}.m.in:not(.cn){border-bottom-left-radius:4px}
.m.me{background:var(--bout);color:#fff;border-bottom-right-radius:6px}.m.me.cp{border-top-right-radius:6px}.m.me:not(.cn){border-bottom-right-radius:4px}
.m.in:not(.cn):before,.m.me:not(.cn):before{content:"";position:absolute;bottom:0;width:10px;height:12px}
.m.in:not(.cn):before{left:-5px;background:var(--bin);clip-path:polygon(100% 0,100% 100%,0 100%,60% 70%)}
.m.me:not(.cn):before{right:-5px;background:#7a56ff;clip-path:polygon(0 0,0 100%,100% 100%,40% 70%)}
.m.st{background:none!important;box-shadow:none;padding:0}.m.st:before{display:none}
.m.big{background:none!important;box-shadow:none;padding:0;font-size:46px;line-height:1.1}.m.big:before{display:none}
.mt{float:right;margin:7px -2px -3px 10px;font-size:11px;opacity:.7;display:inline-flex;gap:3px;align-items:center;line-height:1;white-space:nowrap}
.m.st .mt,.m.big .mt{display:none}
.m:after{content:"";display:block;clear:both}
.tk{display:inline-block}.tk.r{color:#9cf0ff;opacity:1}.m.in .tk.r{color:var(--ac)}
.m a{color:inherit;text-decoration:underline;text-underline-offset:2px}
.wn{display:block;font-size:12.5px;font-weight:800;margin-bottom:2px}
.fw{font-size:12.5px;font-weight:700;opacity:.85;margin-bottom:3px;border-left:3px solid #ffffff88;padding-left:8px}.fw b{display:block}
.m.in .fw{border-color:var(--ac);color:var(--ac)}
.mi{display:block;max-width:100%;width:260px;max-height:320px;object-fit:cover;border-radius:14px;margin:0 0 5px;cursor:zoom-in;background:var(--card2);min-height:70px}
.dsp{align-self:center;margin:12px 0 4px}.dsp span{display:block;background:#0006;color:#fff;font-size:12px;font-weight:700;padding:4px 13px;border-radius:12px;backdrop-filter:blur(6px)}
.rxs{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}.rxs:empty{display:none}
.rx{background:#8a96b32e;border-radius:12px;padding:2px 9px;font-size:13px;font-weight:700;white-space:nowrap}
.rx.me{background:var(--ac);color:#fff}.m.me .rx{background:#ffffff33}.m.me .rx.me{background:#fff;color:#2a5bd8}
.rrow{display:flex;gap:6px;padding:4px 0 12px}.rrow button{flex:1;border:0;border-radius:14px;background:var(--card);font-size:24px;padding:10px 0;cursor:pointer}
.rq{border-left:3px solid var(--ac);padding:2px 8px;margin-bottom:5px;font-size:13px;border-radius:4px;background:#ffffff14;white-space:normal;opacity:.9}
.rq b{display:block;color:var(--ac);font-size:12px}.m.me .rq{border-color:#fff}.m.me .rq b{color:#fff}
.rp{display:flex;align-items:center;gap:10px;padding:8px 14px;background:var(--bg);border-top:1px solid #8a96b31a}
.rp:empty{display:none}
.rp div{flex:1;min-width:0;border-left:3px solid var(--ac);padding-left:10px;font-size:13px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rp b{display:block;color:var(--ac)}.rp button{border:0;background:none;color:var(--mut);font-size:18px;cursor:pointer}
.pnb{display:flex;align-items:center;gap:10px;padding:7px 14px;background:var(--bg);border-bottom:1px solid #8a96b31a;cursor:pointer;flex:none}
.pnb div{flex:1;min-width:0;border-left:3px solid var(--ac);padding-left:10px;font-size:13px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pnb b{display:block;color:var(--ac);font-size:12px}.pnb button{border:0;background:none;color:var(--mut);font-size:18px;cursor:pointer}
.chips{display:flex;gap:8px;padding:8px 12px 0;overflow:auto;background:var(--bg)}.chips:empty{display:none}
.chips button{border:0;border-radius:16px;padding:9px 16px;background:var(--card);color:var(--ac);font:700 14px Manrope,sans-serif;cursor:pointer;flex:none}
.gm{text-align:center;font-size:58px;line-height:1.1}.gm i{display:block;font-size:12px;font-style:normal;opacity:.85;margin-top:4px}
.bar{display:flex;gap:8px;padding:10px 12px max(10px,env(safe-area-inset-bottom));background:var(--bg);align-items:center}
.bar input{flex:1;min-width:0;padding:13px 18px;border-radius:24px}
.fab{position:absolute;right:14px;bottom:96px;width:44px;height:44px;border-radius:50%;border:0;background:var(--card);color:var(--tx);box-shadow:0 6px 22px #0006;display:none;align-items:center;justify-content:center;cursor:pointer;z-index:6}
.fab i{position:absolute;top:-6px;right:-4px;min-width:20px;height:20px;border-radius:10px;background:var(--ac);color:#fff;font:800 11px Manrope;font-style:normal;display:none;align-items:center;justify-content:center;padding:0 5px}
.td i{display:inline-block;width:4px;height:4px;border-radius:50%;background:var(--ac);margin-left:2px;animation:tdt 1.2s infinite}.td i:nth-child(2){animation-delay:.2s}.td i:nth-child(3){animation-delay:.4s}
@keyframes tdt{0%,60%,100%{transform:translateY(0);opacity:.4}30%{transform:translateY(-4px);opacity:1}}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;padding:6px 18px 18px}
.gc{border-radius:24px;padding:20px 8px;text-align:center;background:var(--card);position:relative;overflow:hidden}
.gc:nth-child(3n+1){background:linear-gradient(160deg,#5b8cff33,var(--card))}.gc:nth-child(3n+2){background:linear-gradient(160deg,#9b5cff33,var(--card))}.gc:nth-child(3n){background:linear-gradient(160deg,#34d39933,var(--card))}
.gc .e{font-size:52px}.gc b{display:block;margin-top:4px}.gc small{display:block;color:#f5b942;font-weight:700;margin-top:2px}.gc.p{cursor:pointer}.gc.p:active{transform:scale(.95)}
.sheet{position:absolute;inset:0;background:#000a;display:flex;align-items:flex-end;z-index:9;animation:up .2s}
.sheet>div{background:var(--bg);width:100%;border-radius:28px 28px 0 0;padding-bottom:12px;max-height:88%;overflow:auto}
.xc{display:flex;justify-content:center;padding:10px 0 4px;cursor:pointer}.xc i{display:block;width:46px;height:5px;border-radius:3px;background:var(--card2)}
.burst{position:absolute;left:50%;bottom:90px;font-size:90px;z-index:20;pointer-events:none;animation:bst 1.5s ease-out forwards}
@keyframes bst{from{opacity:1;transform:translate(-50%,0) scale(.5)}to{opacity:0;transform:translate(-50%,-380px) scale(1.5)}}
.cover{background:var(--g);padding:26px 18px 24px;text-align:center;color:#fff;position:relative;border-radius:0 0 34px 34px;overflow:hidden}
.cover>:not(.sd):not(.ib){position:relative}
.cover .ib{position:absolute;right:16px;top:16px;z-index:2}.cover h1{font-size:23px;margin-top:12px}.cover p{margin:4px 0 0;opacity:.88}
.cover h1,.cover p{text-shadow:0 1px 6px #0005}
.cover.nf:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,#0000 30%,#0004);pointer-events:none}
.sd{position:absolute;inset:0;pointer-events:none;overflow:hidden}
.sd:before{content:"";position:absolute;inset:0;background-image:radial-gradient(#fff4 1.4px,transparent 1.6px);background-size:22px 22px;opacity:.45}
.sd span{position:absolute;display:block}
.sd .orb{border-radius:50%;filter:blur(30px);opacity:.55}
.vchip{display:inline-block;margin:8px 0 2px;padding:5px 12px;border-radius:14px;background:#ffffff2e;font-size:13px;font-weight:800}
.vf{vertical-align:-3px;margin-right:6px;cursor:pointer;filter:drop-shadow(0 1px 5px #2a8bff88);animation:vfp 3.2s ease-in-out infinite}
@keyframes vfp{0%,100%{transform:scale(1)}50%{transform:scale(1.1)}}
.vgl{animation:vgl 3.4s ease-in-out infinite}@keyframes vgl{0%{transform:translateX(-30px)}55%,100%{transform:translateX(40px)}}
.vsp{animation:tw 2.6s ease-in-out infinite;transform-box:fill-box;transform-origin:center}
.stl{display:flex;justify-content:center;align-items:center;gap:6px;font-weight:700}
.pav{position:relative;width:116px;margin:0 auto;cursor:pointer}.pav .ava{border:4px solid #ffffff66;box-shadow:0 8px 30px #0004}
.pav i{position:absolute;right:0;bottom:2px;width:36px;height:36px;border-radius:50%;background:#fff;color:var(--ac);display:flex;align-items:center;justify-content:center}
.stats{display:flex;gap:10px;margin:16px 18px 0}.stats div{flex:1;background:var(--card);border-radius:20px;padding:14px 6px;text-align:center;cursor:pointer}
.stats b{display:block;font:700 18px Unbounded,sans-serif}.stats span{color:var(--mut);font-size:12px}
.pg{height:8px;border-radius:4px;background:var(--card2);overflow:hidden;margin:10px 0 6px}.pg i{display:block;height:100%;background:var(--g);border-radius:4px}
.grp{background:var(--card);margin:14px 18px 0;border-radius:22px;overflow:hidden}
.gt{margin:20px 28px 0;color:var(--ac);font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.5px}
.li{display:flex;align-items:center;gap:14px;padding:13px 16px;cursor:pointer;color:var(--mut)}.li+.li{border-top:1px solid #8a96b31a}.li:active{background:var(--card2)}
.li .t{flex:1;min-width:0}.li .t span{display:block;color:var(--tx);font-weight:700}.li .t small{display:block;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ico{width:38px;height:38px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#fff;flex:none}
.c1{background:linear-gradient(135deg,#5b8cff,#3b6fe0)}.c2{background:linear-gradient(135deg,#34d399,#10a77a)}.c3{background:linear-gradient(135deg,#ff9f5b,#f0662d)}
.c4{background:linear-gradient(135deg,#9b5cff,#7138e0)}.c5{background:linear-gradient(135deg,#ffc400,#ff8a00)}.c6{background:linear-gradient(135deg,#4cc9f0,#2a8fd0)}.c7{background:linear-gradient(135deg,#ff5d73,#d93049)}
.sw{width:50px;height:30px;border-radius:15px;background:var(--card2);position:relative;transition:.25s;flex:none}.sw:after{content:"";position:absolute;top:3px;left:3px;width:24px;height:24px;border-radius:50%;background:#fff;transition:.25s}.sw.on{background:var(--ac)}.sw.on:after{left:23px}
.note{color:var(--mut);line-height:1.5;margin:6px 0 14px}.fl{display:block;margin:14px 4px 6px;color:var(--mut);font-size:13px;font-weight:700}
code{background:var(--card);padding:14px;border-radius:14px;display:block;font:700 18px monospace;letter-spacing:1px;word-break:break-all;text-align:center;margin:12px 0;color:var(--ac)}
.empty{text-align:center;color:var(--mut);padding:44px 20px;line-height:1.6}
.apick{width:120px;height:120px;margin:0 auto;border-radius:50%;background:var(--card);border:2px dashed var(--ac);color:var(--ac);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;font-size:12px;font-weight:700;cursor:pointer;overflow:hidden}
.apick img{width:100%;height:100%;object-fit:cover}
/* ── ранги ── */
.rk{display:inline-flex;vertical-align:middle;margin-left:6px;flex:none;cursor:pointer}
.rk8 svg{animation:arb 5s linear infinite}
.rk .hal{transform-box:fill-box;transform-origin:center;animation:rot 14s linear infinite}
.rk .pls{transform-box:fill-box;transform-origin:center;animation:apu 2.4s ease-in-out infinite}
.pm{vertical-align:-3px;margin-left:5px;filter:drop-shadow(0 1px 4px #ffb80088)}
.snw{display:inline-block;margin-left:5px;animation:snr 3s ease-in-out infinite}
@keyframes snr{50%{transform:rotate(25deg) scale(1.18)}}
/* ── NFT: голограммная рамка, лучи, блики, частицы ── */
.nftc{--rad:34px;position:relative;width:132px;height:132px;border-radius:var(--rad);margin:12px auto 6px;overflow:hidden;box-shadow:0 12px 36px var(--c1a),0 0 0 1px #ffffff18}
.nftc.sm{width:88px;height:88px;--rad:26px;margin:0 auto 8px}.nftc.xs{width:60px;height:60px;--rad:18px;margin:0 auto 6px}
.nftc .hb{position:absolute;left:50%;top:50%;width:230%;height:230%;margin:-115% 0 0 -115%;background:conic-gradient(var(--rc),#fff0 16%,var(--c2c) 32%,#fff0 50%,var(--c1c) 68%,#fff0 84%,var(--rc));animation:rot 5s linear infinite}
.nftc .fc{position:absolute;inset:2px;border-radius:calc(var(--rad) - 2px);overflow:hidden;display:flex;align-items:center;justify-content:center;background:radial-gradient(circle at 50% 34%,var(--c1a),transparent 66%),radial-gradient(circle at 50% 118%,var(--c2a),transparent 58%),linear-gradient(165deg,#212a55,#090d1d)}
.nftc .fc:after{content:"";position:absolute;inset:0;background:linear-gradient(115deg,transparent 36%,#ffffff55 50%,transparent 64%);background-size:260% 100%;animation:shn 3.2s linear infinite;z-index:5;pointer-events:none}
.nftc .ar{display:flex;width:70%;height:70%;position:relative;z-index:2;margin-top:-4%}
.nftc .rays{position:absolute;left:50%;top:50%;width:240%;height:240%;margin:-120% 0 0 -120%;background:repeating-conic-gradient(var(--c1a) 0 6deg,transparent 6deg 20deg);animation:rot 24s linear infinite;opacity:.55;-webkit-mask-image:radial-gradient(circle,#000 6%,transparent 52%);mask-image:radial-gradient(circle,#000 6%,transparent 52%)}
.nftc .dots{position:absolute;inset:0;background-image:radial-gradient(#fff5 1px,transparent 1.2px);background-size:11px 11px;opacity:.3}
.nftc .gnd{position:absolute;bottom:13%;left:22%;right:22%;height:9%;border-radius:50%;background:radial-gradient(var(--c1c),transparent 70%);filter:blur(3px);opacity:.85;animation:apu 2.6s ease-in-out infinite;z-index:1}
.nftc .gls{position:absolute;left:0;right:0;top:0;height:42%;background:linear-gradient(180deg,#ffffff30,transparent);z-index:3;pointer-events:none}
.nftc .pt{position:absolute;bottom:-4px;width:3px;height:3px;border-radius:50%;background:#fff;box-shadow:0 0 6px #fff;opacity:0;animation:rise 3.6s linear infinite;z-index:3}
@keyframes rise{0%{transform:translateY(0);opacity:0}20%{opacity:.95}100%{transform:translateY(-130px);opacity:0}}
.nftc.sm .pt,.nftc.xs .pt{animation-name:riseS}
@keyframes riseS{0%{transform:translateY(0);opacity:0}20%{opacity:.95}100%{transform:translateY(-70px);opacity:0}}
.nftc .rt{position:absolute;bottom:6px;left:0;right:0;text-align:center;font:800 9px Manrope,sans-serif;font-style:normal;letter-spacing:1px;text-transform:uppercase;color:var(--rc);z-index:4;text-shadow:0 0 8px #000,0 0 10px var(--rc)}
.nftc.sm .rt,.nftc.xs .rt{display:none}
.nftc.r-l .fc:before,.nftc.r-m .fc:before{content:"";position:absolute;inset:0;background:radial-gradient(circle at 50% 45%,var(--c1a),transparent 62%);animation:apu 2.2s ease-in-out infinite;z-index:1}
.nftc.r-m .hb{animation-duration:2.6s}
.sp{position:absolute;color:#fff;font-style:normal;opacity:0;animation:tw 2.2s ease-in-out infinite;z-index:3}
.s1{top:10%;left:14%}.s2{top:18%;right:12%;animation-delay:.7s}.s3{bottom:22%;left:18%;animation-delay:1.4s}.s4{bottom:26%;right:14%;animation-delay:1s}
@keyframes tw{0%,100%{opacity:0;transform:scale(.3) rotate(0)}50%{opacity:1;transform:scale(1.2) rotate(90deg)}}
@keyframes shn{from{background-position:160% 0}to{background-position:-90% 0}}
.nbd{display:inline-block;vertical-align:-4px;margin-left:5px;cursor:pointer}
.a-float{animation:afl 2.6s ease-in-out infinite}@keyframes afl{50%{transform:translateY(-9%)}}
.a-spin{animation:asp 4s linear infinite}@keyframes asp{to{transform:rotateY(360deg)}}
.a-pulse{animation:apu 1.4s ease-in-out infinite}@keyframes apu{50%{transform:scale(1.22)}}
.a-glow{animation:agl 2s ease-in-out infinite}@keyframes agl{50%{filter:drop-shadow(0 0 14px #fff) brightness(1.3)}}
.a-swing{transform-origin:50% 0;animation:asw 2s ease-in-out infinite}@keyframes asw{0%,100%{transform:rotate(-14deg)}50%{transform:rotate(14deg)}}
.a-rainbow{animation:arb 3s linear infinite}@keyframes arb{to{filter:hue-rotate(360deg)}}
.spin{margin-top:14px;text-align:center;background:linear-gradient(160deg,#9b5cff33,var(--card));border-radius:24px;padding:20px}
.reel{position:relative;overflow:hidden;height:112px;border-radius:20px;background:var(--card);margin:6px 0 14px}
.strip{display:flex;transition:transform 4.2s cubic-bezier(.12,.62,.08,1);will-change:transform}
.ri{width:100px;height:112px;flex:none;padding:8px;display:flex;align-items:center;justify-content:center}
.ri>div{width:84px;height:84px;border-radius:22px;background:radial-gradient(circle at 50% 40%,var(--c1a),transparent 72%),linear-gradient(160deg,#1d2544,#0c1124);padding:8px;border:1.5px solid var(--rc);box-shadow:0 0 14px var(--c1a)}
.mark{position:absolute;left:50%;top:0;bottom:0;width:3px;margin-left:-1px;background:#fff;box-shadow:0 0 12px #fff,0 0 24px var(--ac)}
.nuu{display:inline-block;margin-top:6px;padding:4px 14px;border-radius:14px;background:#fff;color:#2a7bff;font-weight:800;font-size:14px}
.rkl{display:flex;align-items:center;gap:14px;padding:11px 14px;border-radius:18px;background:var(--card);margin-bottom:8px;border:1.5px solid transparent}.rkl.cur{border-color:var(--ac);background:linear-gradient(135deg,#5b8cff22,var(--card))}
.rkl b{display:block}.rkl small{color:var(--mut)}
/* ── заморозка ── */
.fzb{display:flex;gap:12px;align-items:center;padding:12px 16px;background:linear-gradient(135deg,#4cc9f0,#5b8cff 55%,#9b5cff);color:#fff;cursor:pointer;flex:none;box-shadow:0 6px 24px #4cc9f066;position:relative;z-index:6;overflow:hidden}
.fzb span{flex:1;font-size:13px;line-height:1.35;position:relative}.fzb b{display:block;font-size:15px}.fzb em{font-style:normal;font-size:28px;animation:snr 3s ease-in-out infinite;position:relative}
.snowl{position:absolute;top:-10px;color:#fff;font-style:normal;opacity:.7;animation:fall 5s linear infinite}.snowl:nth-child(1){left:30%}.snowl.s2{left:70%;animation-delay:-2s;font-size:12px}
.fzc{margin:auto;text-align:center;padding:34px 26px 30px;border-radius:30px;max-width:330px;background:linear-gradient(160deg,#4cc9f033,#9b5cff22,var(--card));border:1px solid #4cc9f055;position:relative;overflow:hidden;box-shadow:0 14px 44px #4cc9f033}
.fzc .fi{font-size:76px;line-height:1;animation:snr 3s ease-in-out infinite;position:relative}
.fzc h2{font-size:20px;margin:12px 0 8px;position:relative}.fzc p{color:var(--mut);margin:0;line-height:1.55;position:relative}
.fzc .fb{display:inline-block;margin-top:14px;padding:7px 16px;border-radius:14px;background:#4cc9f022;color:#4cc9f0;font-weight:800;font-size:13px;position:relative}
.fl2{position:absolute;top:-24px;color:#bfe9ff;animation:fall linear infinite;opacity:.85}
@keyframes fall{to{transform:translateY(420px) rotate(360deg)}}
.viewer{position:absolute;inset:0;background:#000f;z-index:40;display:flex;align-items:center;justify-content:center;animation:up .2s}
.viewer img{max-width:100%;max-height:100%}
.viewer button{position:absolute;top:max(14px,env(safe-area-inset-top));right:14px;border:0;width:42px;height:42px;border-radius:14px;background:#ffffff2e;color:#fff;font-size:20px;cursor:pointer}
.pv{display:block;width:100%;max-height:48vh;object-fit:contain;border-radius:16px;margin:6px 0 12px;background:var(--card)}
.bgp{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.bgp div{height:90px;border-radius:18px;cursor:pointer;display:flex;align-items:flex-end;padding:8px;color:#fff;font-weight:800;font-size:13px;border:2px solid transparent;text-shadow:0 1px 4px #0008}.bgp div.on{border-color:var(--ac)}
</style></head><body><div id="app"></div>
<script>
const $=s=>document.querySelector(s),A=$('#app');
const I={chat:'<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
gift:'<polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/>',
sliders:'<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
user:'<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
back:'<polyline points="15 18 9 12 15 6"/>',chev:'<polyline points="9 18 15 12 9 6"/>',down:'<polyline points="6 9 12 15 18 9"/>',
more:'<circle cx="12" cy="5" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="19" r="1.6"/>',
eye:'<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
eyeoff:'<path d="M17.9 17.9A10.9 10.9 0 0 1 12 20c-7 0-11-8-11-8a18.5 18.5 0 0 1 5.1-5.9M9.9 4.2A9.1 9.1 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.2 3.2M14.1 14.1a3 3 0 1 1-4.2-4.2"/><line x1="1" y1="1" x2="23" y2="23"/>',
send:'<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
camera:'<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
lock:'<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
key:'<path d="M21 2l-2 2m-7.6 7.6a5.5 5.5 0 1 1-7.8 7.8 5.5 5.5 0 0 1 7.8-7.8zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3"/>',
mail:'<path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><polyline points="22 6 12 13 2 6"/>',
phone:'<rect x="5" y="2" width="14" height="20" rx="2"/><line x1="12" y1="18" x2="12.01" y2="18"/>',
at:'<circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.9 7.9"/>',
shield:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
moon:'<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
info:'<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
out:'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
edit:'<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
star:'<polygon points="12 2 15 8.5 22 9.3 17 14 18.2 21 12 17.7 5.8 21 7 14 2 9.3 9 8.5 12 2"/>',
monitor:'<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
trash:'<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
palette:'<circle cx="13.5" cy="6.5" r="1.5"/><circle cx="17.5" cy="10.5" r="1.5"/><circle cx="8.5" cy="7.5" r="1.5"/><circle cx="6.5" cy="12.5" r="1.5"/><path d="M12 2a10 10 0 0 0 0 20c1.1 0 2-.9 2-2 0-.5-.2-1-.5-1.3-.3-.4-.5-.8-.5-1.3 0-1.1.9-2 2-2h2.4a4.7 4.7 0 0 0 4.7-4.7C22 6 17.5 2 12 2z"/>',
eyeg:'<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
msg:'<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.2A8.4 8.4 0 1 1 21 11.5z"/>'};
const ic=(n,s=22)=>`<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I[n]}</svg>`;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const lk=s=>s.replace(/(https?:\/\/[^\s<]+)/g,'<a href="$1" target="_blank" rel="noopener" onclick="event.stopPropagation()">$1</a>');
const ava=(u,s=52)=>{const st=`width:${s}px;height:${s}px;font-size:${s*.42}px`;
 if(u.frozen&&!isSelf(u))return `<div class="ava" style="${st};background:linear-gradient(135deg,#d6f3ff,#6aa8ff 60%,#9b86ff);font-size:${s*.5}px">❄️</div>`;
 if(u.gone&&!isSelf(u))return `<div class="ava" style="${st};background:linear-gradient(135deg,#8a96b3,#5b6785);font-size:${s*.5}px">👻</div>`;
 return u.av?`<div class="ava" style="${st}"><img src="${u.av}"></div>`:`<div class="ava" style="${st};background:linear-gradient(135deg,hsl(${u.id*67%360} 75% 58%),hsl(${(u.id*67+50)%360} 70% 42%))">${esc((u.name||u.nick||'?')[0].toUpperCase())}</div>`};
const sav=s=>`<div class="ava" style="width:${s}px;height:${s}px;font-size:${s*.45}px;background:var(--g)">⭐</div>`;
const isSelf=u=>ME&&u.id==ME.id;
const nameOf=u=>isSelf(u)?'⭐ Избранное':u.name;
const avOf=(u,s)=>isSelf(u)?sav(s):ava(u,s);
const isOn=u=>!u.bot&&!u.kind&&!u.frozen&&!u.gone&&!isSelf(u)&&u.seen&&Date.now()/1000-u.seen<75;
const avd=(u,s)=>`<span class="avw">${avOf(u,s)}${isOn(u)?'<i class="od"></i>':''}</span>`;
let ME=null,GIFTS=[],NFTS=[],ANIMS=[],ST=[],RE=['👍','❤️','😂','😮','😢','🔥'],SP=100,RP={},PEER=null,GID='',tab='chats',timer=null,curPeer=null,R={},REPLY=null,EDIT=0,SB=0,LVT=[0,100,300,700,1500,3000,6000,12000,25000,50000,100000,200000],RN=['Новичок','Участник','Активный','Мастер','Эксперт','Легенда','Титан','Бессмертный','Властелин','Архонт','Небожитель','Абсолют'],FT='all',CH=[],TYP=[],NEWC=0,PLEN=0,RESTORED=0,SQ='',PIN=null,LD=null;
try{if(localStorage.nova_theme=='light')document.body.classList.add('light')}catch(e){}
async function api(p,b){try{const r=await fetch('/api/'+p,b===undefined?{credentials:'same-origin'}:{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return await r.json()}catch(e){return{error:'Ошибка соединения с сервером'}}}
const stop=()=>{clearInterval(timer);timer=null};
async function refreshMe(){const d=await api('me');if(d.user){ME=d.user;SB=d.sb||SB}}
async function boot(){const d=await api('me');GIFTS=d.gifts||[];GID=d.gid||'';ST=d.stickers||[];NFTS=d.nfts||[];ANIMS=d.anims||[];SP=d.sp;RP=d.rp||{};RE=d.reacts||RE;SB=d.sb||0;LVT=d.lv||LVT;RN=d.rn||RN;ME=d.user||null;ME?(main(),devInfo(),RESTORED&&(RESTORED=0,toast('🎉 С возвращением! Удаление отменено'))):welcome()}
setInterval(async()=>{if(!ME)return;const was=ME.frozen,wl=ME.appeal_left;await refreshMe();if(ME&&(was!==ME.frozen||(ME.frozen&&wl!==ME.appeal_left))){if(curPeer)openChat(curPeer);else if($('#v'))main()}},9000);
function pick(cb){const f=document.createElement('input');f.type='file';f.accept='image/*';
 f.onchange=()=>{if(!f.files[0])return;const r=new FileReader();r.onload=()=>{const im=new Image();im.onload=()=>{const s=Math.min(im.width,im.height),c=document.createElement('canvas');c.width=c.height=320;
 c.getContext('2d').drawImage(im,(im.width-s)/2,(im.height-s)/2,s,s,0,0,320,320);cb(c.toDataURL('image/jpeg',.85))};im.src=r.result};r.readAsDataURL(f.files[0])};f.click()}
function sheet(h){const s=document.createElement('div');s.className='sheet';s.onclick=e=>e.target==s&&s.remove();s.innerHTML=`<div><div class="xc" onclick="this.closest('.sheet').remove()"><i></i></div>${h}</div>`;A.appendChild(s);return s}
function confirmBox(em,title,text,yes,fn,danger){const s=sheet(`<div style="text-align:center;padding:10px 22px 18px"><div style="font-size:64px;line-height:1.1">${em}</div><h2 style="font-size:20px;margin:12px 0 8px">${title}</h2><p class="note" style="margin:0 0 18px">${text}</p><button class="btn ${danger?'bad':''}" data-y="1">${yes}</button><button class="btn gl" style="margin-top:10px" data-n="1">Назад</button></div>`);
 s.querySelector('[data-n]').onclick=()=>s.remove();s.querySelector('[data-y]').onclick=async()=>{s.remove();await fn()}}
const hm=ts=>new Date(ts*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
const when=ts=>{const d=new Date(ts*1000);return d.toDateString()==new Date().toDateString()?'сегодня в '+hm(ts):d.toLocaleDateString([],{day:'2-digit',month:'2-digit'})+' в '+hm(ts)};
const seenTxt=u=>{if(u.frozen&&!isSelf(u))return'❄️ аккаунт недоступен';if(u.gone&&!isSelf(u))return'аккаунт недоступен';if(u.bot)return'бот';if(u.hs)return'был(а) недавно';if(!u.seen)return'был(а) давно';
 const df=Date.now()/1000-u.seen;if(df<75)return'в сети';if(df<3600)return'был(а) '+Math.max(1,Math.round(df/60))+' мин. назад';const d=new Date(u.seen*1000),y=new Date(Date.now()-864e5);
 if(d.toDateString()==new Date().toDateString())return'был(а) сегодня в '+hm(u.seen);if(d.toDateString()==y.toDateString())return'был(а) вчера в '+hm(u.seen);return'был(а) '+when(u.seen)};
const stx=p=>isSelf(p)?'сохранённые сообщения':p.kind?p.bio:seenTxt(p);
const dayLbl=ts=>{const d=new Date(ts*1000),n=new Date(),y=new Date(Date.now()-864e5);if(d.toDateString()==n.toDateString())return'Сегодня';if(d.toDateString()==y.toDateString())return'Вчера';return d.toLocaleDateString([],{day:'numeric',month:'long'})};

/* ───── NFT-арты (SVG) ───── */
function nm(k){return NFTS.find(x=>x.id==k)||{c:['#555','#888'],n:'?',r:'',w:1}}
const RC={'Редкий':'#5b8cff','Эпический':'#b36bff','Легендарный':'#ffc400','Мифический':'#ff5a3c'};
let GI=0;
const ART={
orb:(F,Rr)=>`<path d="M28 88h44l-7-14H35z" fill="#2a2f4d"/><path d="M33 80h34l-3-6H36z" fill="#fff" opacity=".12"/><circle cx="50" cy="46" r="34" ${Rr}/><circle cx="50" cy="46" r="34" fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="1.5"/><path d="M22 52q14-18 28 0t28 0" stroke="#fff" stroke-opacity=".5" stroke-width="3" fill="none"/><path d="M28 36q22-14 44 0" stroke="#fff" stroke-opacity=".25" stroke-width="2" fill="none"/><ellipse cx="38" cy="29" rx="11" ry="5.5" fill="#fff" opacity=".8" transform="rotate(-30 38 29)"/><circle cx="62" cy="58" r="2.4" fill="#fff" opacity=".8"/><circle cx="44" cy="62" r="1.6" fill="#fff" opacity=".7"/>`,
crystal:(F)=>`<path d="M18 38L33 14h34l15 24L50 90z" ${F}/><path d="M18 38h64L50 90z" fill="#fff" opacity=".18"/><path d="M33 14l17 24 17-24z" fill="#fff" opacity=".42"/><path d="M33 14L18 38h64L67 14zM50 38L34 38M50 38v52M18 38l32 52M82 38L50 90" stroke="#fff" stroke-opacity=".75" stroke-width="1.5" fill="none" stroke-linejoin="round"/><path d="M40 24l6 8" stroke="#fff" stroke-width="3" stroke-linecap="round" opacity=".9"/>`,
planet:(F,Rr)=>`<ellipse cx="50" cy="52" rx="45" ry="12" transform="rotate(-22 50 52)" fill="none" stroke="#fff" stroke-opacity=".4" stroke-width="6"/><circle cx="50" cy="50" r="27" ${Rr}/><path d="M32 40q18 7 36-4M25 57q25 9 50-4M30 66q20 5 40-2" stroke="#fff" stroke-opacity=".3" stroke-width="4" fill="none" stroke-linecap="round"/><ellipse cx="40" cy="38" rx="9" ry="5" fill="#fff" opacity=".45" transform="rotate(-30 40 38)"/><path d="M5 53A45 12 0 0 0 95 53" transform="rotate(-22 50 52)" fill="none" stroke="#fff" stroke-opacity=".95" stroke-width="6" stroke-linecap="round"/><circle cx="14" cy="18" r="2" fill="#fff"/><circle cx="86" cy="82" r="2.5" fill="#fff"/><circle cx="84" cy="16" r="1.6" fill="#fff"/><circle cx="20" cy="82" r="1.4" fill="#fff"/>`,
moon:(F)=>`<circle cx="50" cy="50" r="42" fill="none" stroke="#fff" stroke-opacity=".14" stroke-width="1.5" stroke-dasharray="2 5"/><path d="M62 10A40 40 0 1 0 90 66 32 32 0 0 1 62 10z" ${F} stroke="#fff" stroke-opacity=".85" stroke-width="2" stroke-linejoin="round"/><path d="M62 10A40 40 0 0 0 28 26 34 34 0 0 1 62 10z" fill="#fff" opacity=".4"/><circle cx="32" cy="58" r="5" fill="#fff" opacity=".22"/><circle cx="44" cy="76" r="3" fill="#fff" opacity=".22"/><circle cx="26" cy="40" r="2.4" fill="#fff" opacity=".22"/><path d="M78 20l2.4 5.6 5.6 2.4-5.6 2.4L78 36l-2.4-5.6L70 28l5.6-2.4z" fill="#fff"/><circle cx="88" cy="42" r="2" fill="#fff"/><circle cx="72" cy="86" r="1.6" fill="#fff"/>`,
lotus:(F)=>`<g transform="translate(0 6)">${[-72,72,-48,48,-24,24,0].map(a=>`<ellipse cx="50" cy="40" rx="10" ry="28" transform="rotate(${a} 50 68)" ${F} stroke="#fff" stroke-opacity=".7" stroke-width="1.4" opacity=".95"/>`).join('')}<circle cx="50" cy="64" r="9" fill="#ffe27a"/><circle cx="50" cy="64" r="9" fill="none" stroke="#fff" stroke-width="1.5"/><circle cx="47" cy="61" r="2.5" fill="#fff" opacity=".8"/></g><path d="M20 90q30-10 60 0" stroke="#fff" stroke-opacity=".4" stroke-width="2.5" fill="none" stroke-linecap="round"/>`,
star:(F)=>{const p=Array.from({length:10},(_,i)=>{const r=i%2?17:41,a=Math.PI*i/5-Math.PI/2;return(50+r*Math.cos(a)).toFixed(1)+','+(54+r*Math.sin(a)).toFixed(1)}).join(' ');return `<circle cx="50" cy="52" r="40" ${F} opacity=".22"/><circle cx="50" cy="52" r="33" fill="none" stroke="#fff" stroke-opacity=".3" stroke-dasharray="3 5"/><polygon points="${p}" ${F} stroke="#fff" stroke-width="2.5" stroke-linejoin="round"/><polygon points="${p}" fill="#fff" opacity=".3" transform="translate(50 54) scale(.5) translate(-50 -54)"/><path d="M50 14v40M12 44l38 10M88 44L50 54M26 86l24-32M74 86L50 54" stroke="#fff" stroke-opacity=".5" stroke-width="1.2"/>`},
crown:(F)=>`<path d="M14 72L10 30l24 20 16-28 16 28 24-20-4 42z" ${F} stroke="#fff" stroke-opacity=".8" stroke-width="2" stroke-linejoin="round"/><path d="M14 72L10 30l24 20 16-28v50z" fill="#fff" opacity=".18"/><rect x="14" y="72" width="72" height="13" rx="4" ${F} stroke="#fff" stroke-opacity=".8" stroke-width="2"/><circle cx="50" cy="61" r="5.5" fill="#ff4d6d"/><circle cx="29" cy="63" r="3.6" fill="#4cc9f0"/><circle cx="71" cy="63" r="3.6" fill="#4cc9f0"/><circle cx="10" cy="30" r="4.5" fill="#fff"/><circle cx="90" cy="30" r="4.5" fill="#fff"/><circle cx="50" cy="20" r="4.5" fill="#fff"/><path d="M20 78h60" stroke="#fff" stroke-opacity=".5" stroke-width="2" stroke-dasharray="2 5" stroke-linecap="round"/>`,
diamond:(F)=>`<path d="M26 14h48l20 24-44 52L6 38z" ${F} stroke="#fff" stroke-opacity=".85" stroke-width="2" stroke-linejoin="round"/><path d="M26 14l24 24H6z" fill="#fff" opacity=".3"/><path d="M50 38h44L50 90z" fill="#000" opacity=".14"/><path d="M6 38h88M26 14l24 24 24-24M50 38v52M26 14l-6 24 30 52M74 14l6 24-30 52" stroke="#fff" stroke-opacity=".6" stroke-width="1.3" fill="none" stroke-linejoin="round"/><path d="M34 22l5 6" stroke="#fff" stroke-width="3" stroke-linecap="round"/><path d="M84 8l2.2 5.2 5.2 2.2-5.2 2.2L84 23l-2.2-5.2-5.2-2.2 5.2-2.2z" fill="#fff"/>`,
butterfly:(F)=>`<g ${F} stroke="#fff" stroke-opacity=".8" stroke-width="1.5" stroke-linejoin="round">${['','translate(100 0) scale(-1 1)'].map(t=>`<g transform="${t}"><path d="M48 48C38 12 6 12 10 40c2 11 21 15 38 8z"/><path d="M48 52C33 54 14 63 22 82c6 12 23-4 26-28z"/><circle cx="26" cy="32" r="6" fill="#fff" fill-opacity=".35" stroke="none"/><circle cx="30" cy="70" r="4" fill="#fff" fill-opacity=".35" stroke="none"/></g>`).join('')}</g><rect x="46.5" y="32" width="7" height="46" rx="3.5" fill="#fff"/><path d="M48 33q-6-12-13-14M52 33q6-12 13-14" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round"/><circle cx="35" cy="19" r="2" fill="#fff"/><circle cx="65" cy="19" r="2" fill="#fff"/>`,
phoenix:(F)=>`<path d="M50 54C36 50 14 42 6 18c14 8 26 8 34 14-2-8-8-14-8-22 10 6 16 14 18 26z" ${F} stroke="#fff" stroke-opacity=".6" stroke-width="1.6" stroke-linejoin="round"/><path d="M50 54C64 50 86 42 94 18c-14 8-26 8-34 14 2-8 8-14 8-22-10 6-16 14-18 26z" ${F} stroke="#fff" stroke-opacity=".6" stroke-width="1.6" stroke-linejoin="round"/><path d="M50 8C57 28 80 38 76 62 74 80 62 93 50 93 38 93 26 80 24 62 22 48 34 44 38 28 42 34 46 24 50 8z" ${F} stroke="#fff" stroke-opacity=".7" stroke-width="2" stroke-linejoin="round"/><path d="M50 40C54 54 66 58 64 70 63 80 56 87 50 87 42 87 36 80 36 70 36 62 44 60 46 50z" fill="#ffe27a" opacity=".95"/><path d="M50 62C53 68 58 70 57 76 56 81 53 84 50 84 46 84 43 81 43 76 43 72 48 70 50 62z" fill="#fff"/><circle cx="50" cy="30" r="2.4" fill="#fff"/>`};
function art(k){const n=nm(k),i='g'+(GI++);
 return `<svg viewBox="0 0 100 100" width="100%" height="100%" style="filter:drop-shadow(0 3px 7px ${n.c[1]}aa)"><defs><linearGradient id="${i}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${n.c[0]}"/><stop offset="1" stop-color="${n.c[1]}"/></linearGradient><radialGradient id="${i}r" cx=".35" cy=".3" r=".85"><stop offset="0" stop-color="#fff" stop-opacity=".9"/><stop offset=".35" stop-color="${n.c[0]}"/><stop offset="1" stop-color="${n.c[1]}"/></radialGradient></defs>${(ART[k]||ART.orb)(`fill="url(#${i})"`,`fill="url(#${i}r)"`)}</svg>`}
const nftCard=(k,a,sz)=>{const n=nm(k),rc=RC[n.r]||'#fff',rcl=n.r=='Мифический'?'r-m':n.r=='Легендарный'?'r-l':'';
 return `<div class="nftc ${sz||''} ${rcl}" style="--c1a:${n.c[0]}77;--c2a:${n.c[1]}55;--c1c:${n.c[0]};--c2c:${n.c[1]};--rc:${rc}"><i class="hb"></i><div class="fc"><i class="rays"></i><i class="dots"></i><i class="gnd"></i><span class="ar a-${a}">${art(k)}</span><i class="gls"></i>${[8,24,41,58,74,90].map((l,i)=>`<i class="pt" style="left:${l}%;animation-delay:${-i*.6}s"></i>`).join('')}<i class="sp s1">✦</i><i class="sp s2">✧</i><i class="sp s3">✦</i><i class="sp s4">✧</i><em class="rt">${n.r}</em></div></div>`};
const nb=(n,s=18)=>n?`<span class="nbd a-${n.anim}" onclick="nftShow('${n.kind}','${n.anim}',event)" style="width:${s}px;height:${s}px">${art(n.kind)}</span>`:'';

/* ✅ галочка «Проверено NovaGram» */
let VI=0;
const SEAL=Array.from({length:32},(_,i)=>{const r=i%2?9.9:11.6,a=Math.PI*i/16;return(12+r*Math.cos(a)).toFixed(2)+','+(12+r*Math.sin(a)).toFixed(2)}).join(' ');
const vf=(u,s=16)=>{if(!u||!u.ver)return'';const g='vg'+(VI++);
 return `<svg class="vf" onclick="verInfo(event)" width="${s}" height="${s}" viewBox="0 0 24 24"><defs><linearGradient id="${g}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7ef6ff"/><stop offset=".5" stop-color="#2a8bff"/><stop offset="1" stop-color="#7a4bff"/></linearGradient><clipPath id="${g}c"><polygon points="${SEAL}"/></clipPath></defs><polygon points="${SEAL}" fill="url(#${g})" stroke="url(#${g})" stroke-width="1.2" stroke-linejoin="round"/><g clip-path="url(#${g}c)"><rect class="vgl" x="-10" y="-2" width="7" height="28" fill="#fff" opacity=".55" transform="skewX(-22)"/></g><circle cx="12" cy="12" r="8.4" fill="none" stroke="#fff" stroke-opacity=".4" stroke-width=".7"/><path d="M7.6 12.6l3.1 3.1 5.8-6.3" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><path class="vsp" d="M19.5 3v3M18 4.5h3" stroke="#fff" stroke-width="1.1" stroke-linecap="round"/></svg>`};
const pm=(p,s=16)=>{if(!p)return'';const g='pg'+(VI++);return `<svg class="pm" width="${s}" height="${s}" viewBox="0 0 24 24"><defs><linearGradient id="${g}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff3a0"/><stop offset=".5" stop-color="#ffc400"/><stop offset="1" stop-color="#ff8a00"/></linearGradient></defs><path fill="url(#${g})" stroke="#ff9100" stroke-width="1" stroke-linejoin="round" d="M12 2l3 6.5 7 .8-5.2 4.8 1.4 7L12 17.5 5.8 21l1.4-7L2 9.3l7-.8z"/><path d="M12 5l1.6 3.6" stroke="#fff" stroke-width="1.4" stroke-linecap="round" opacity=".8"/></svg>`};

/* 🏅 12 рангов: своя форма, градиент, кольцо, блик, вращающийся ореол */
let RI=0;
const RS=[['#c3cbe0','#6d7a99','#f2f5fc'],['#5af0b8','#0e9f8e','#c8fff2'],['#74a8ff','#3b5bff','#d6e4ff'],['#c58bff','#7a3cff','#ecd9ff'],['#ffb347','#ff5a2d','#ffe3c2'],['#ffe680','#ff9a00','#fff7d0'],['#ff7ad9','#b100ff','#ffd6f6'],['#6df0ff','#ff4de3','#ffffff'],['#ff9a9a','#d4145a','#ffe0ea'],['#8affd6','#009e9e','#e0fff6'],['#e6c8ff','#6a00ff','#ffffff'],['#fff6a8','#ffb300','#ffffff']];
const pol=(n,ri,r)=>Array.from({length:n*2},(_,i)=>{const rr=i%2?ri*r:r,a=Math.PI*i/n-Math.PI/2;return(50+rr*Math.cos(a)).toFixed(1)+','+(50+rr*Math.sin(a)).toFixed(1)}).join(' ');
const RSH=['<circle cx="50" cy="50" r="42"/>',
 `<polygon points="${pol(3,1,46)}"/>`,
 '<path d="M50 6L88 20V50C88 74 71 89 50 96C29 89 12 74 12 50V20Z"/>',
 `<polygon points="${pol(8,.82,47)}"/>`,
 `<polygon points="${pol(2,1,48)}"/>`,
 `<polygon points="${pol(12,.84,48)}"/>`,
 `<polygon points="${pol(6,.8,48)}"/>`,
 `<polygon points="${pol(16,.82,48)}"/>`,
 `<polygon points="${pol(5,.55,50)}"/>`,
 `<polygon points="${pol(20,.88,48)}"/>`,
 `<polygon points="${pol(7,.62,50)}"/>`,
 `<polygon points="${pol(24,.84,49)}"/>`];
const rk=(l,s=22,id)=>{l=Math.max(1,Math.min(l||1,RS.length));const c=RS[l-1],g='rk'+(RI++),sh=RSH[l-1];
 return `<span class="rk ${l>=11?'rk8':''}" ${id===null?'':`onclick="rankInfo(${id||0},${l},event)"`} style="width:${s}px;height:${s}px;filter:drop-shadow(0 2px ${l>=9?11:7}px ${c[0]}${l>=9?'dd':'aa'})"><svg viewBox="0 0 100 100" width="100%" height="100%"><defs><linearGradient id="${g}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c[0]}"/><stop offset="1" stop-color="${c[1]}"/></linearGradient><linearGradient id="${g}s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".7"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>${l>=6?`<circle class="hal" cx="50" cy="50" r="49" fill="none" stroke="${c[2]}" stroke-opacity=".55" stroke-width="1.6" stroke-dasharray="${l>=9?'2 5':'4 6'}"/>`:''}<g fill="url(#${g})" stroke="${c[2]}" stroke-width="5" stroke-linejoin="round" ${l>=9?'class="pls"':''}>${sh}</g><g fill="url(#${g}s)" stroke="none">${sh}</g><circle cx="50" cy="50" r="27" fill="none" stroke="${c[2]}" stroke-opacity=".55" stroke-width="2.5"/>${l>=4?`<circle cx="50" cy="50" r="33" fill="none" stroke="#fff" stroke-opacity=".22" stroke-width="1"/>`:''}<text x="50" y="53" text-anchor="middle" dominant-baseline="central" font-size="${l>9?34:40}" font-weight="800" fill="#fff" stroke="#0006" stroke-width="3" paint-order="stroke" font-family="Manrope,sans-serif">${l}</text></svg></span>`};
const bd=u=>pm(u.prem)+(u.lvl?rk(u.lvl,18,u.id):'')+nb(u.nft)+(u.frozen?'<span class="snw">❄️</span>':'');
/* фон профиля: цвет NFT + узор из NFT */
const cvs=n=>n?`background:linear-gradient(160deg,${nm(n.kind).c[0]},${nm(n.kind).c[1]})`:'';
const PAT=(()=>{const a=[];for(let r=0;r<7;r++){const y=r*14+2;a.push([3+(r%2)*9,y,22+(r*7)%16,.5],[89-(r%2)*9,y+6,22+(r*5)%16,.5]);if(r%2==0)a.push([30+r*3,y+(r<3?-2:10),16,.3],[58-r*3,y+(r<3?10:-2),16,.3])}return a})();
const sides=n=>n?`<div class="sd"><span class="orb" style="left:-10%;top:-10%;width:50%;height:50%;background:${nm(n.kind).c[1]}"></span><span class="orb" style="right:-10%;bottom:-10%;width:50%;height:50%;background:${nm(n.kind).c[0]}"></span>${PAT.map((p,i)=>`<span class="a-float" style="left:${p[0]}%;top:${p[1]}%;width:${p[2]}px;height:${p[2]}px;opacity:${p[3]};animation-delay:${i*.27}s;transform:rotate(${(i*37)%50-25}deg)">${art(n.kind)}</span>`).join('')}</div>`:'';
function nftShow(k,a,e){if(e)e.stopPropagation();const n=nm(k);sheet(`<div style="text-align:center;padding:12px 18px 10px">${nftCard(k,a)}<h2 style="font-size:20px">${n.n}</h2><div style="color:${RC[n.r]};font-weight:800;margin:6px 0">${n.r}</div></div>`)}
function verInfo(e){if(e)e.stopPropagation();sheet(`<div style="text-align:center;padding:16px 18px 14px">${vf({ver:1},84)}<h2 style="font-size:20px;margin-top:14px">Проверено NovaGram</h2><p class="note">Этот аккаунт подтверждён NovaGram. Получить галочку можно у бота @Galochka_bot.</p></div>`)}

/* ───── ВХОД / РЕГИСТРАЦИЯ ───── */
const blobs='<div class="blob" style="width:300px;height:300px;background:#5b8cff;top:-80px;left:-80px"></div><div class="blob" style="width:260px;height:260px;background:#9b5cff;bottom:-60px;right:-70px;animation-delay:-4s"></div><div class="blob" style="width:200px;height:200px;background:#ff5cd0;top:40%;right:-90px;animation-delay:-2s;opacity:.3"></div>';
const steps=n=>`<div class="steps">${[1,2,3].map(i=>`<i class="${i<=n?'on':''}"></i>`).join('')}</div>`;
const pwi=(id,ph)=>`<div class="iw"><input id="${id}" type="password" placeholder="${ph}" autocomplete="off"><button type="button" class="eye" onclick="eye('${id}',this)">${ic('eye',20)}</button></div>`;
function eye(id,b){const i=document.getElementById(id),h=i.type=='password';i.type=h?'text':'password';b.innerHTML=ic(h?'eyeoff':'eye',20)}
function pwMeter(){const v=($('#pw')||{}).value||'',m=$('#pm');if(!m)return;let s=0;if(v.length>=6)s++;if(v.length>=10)s++;if(/[A-Z]/.test(v)&&/[a-z]/.test(v))s++;if(/\d/.test(v)&&/[^\w]|_/.test(v))s++;s=v?Math.max(1,s):0;m.style.width=s*25+'%';m.style.background=['','#ff5d73','#ff9f5b','#ffc400','#34d399'][s]}
function welcome(){stop();A.innerHTML=`${blobs}<div class="fbub o" style="right:8%;top:9%">Привет! 👋</div><div class="fbub i" style="left:6%;top:19%;animation-delay:-2s">Как дела? ✨</div><div class="fbub o" style="right:12%;top:30%;animation-delay:-4s">Дарю 🌹 +10 ★</div><div class="center"><div class="logo">${ic('msg',54)}</div><h1 class="t1">Nova</h1><p class="sub">Быстрый и красивый мессенджер.<br>Чаты, NFT, боты и подарки.</p>
<div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap"><span class="chip">💎 NFT</span><span class="chip">⭐ Ранги</span><span class="chip">🤖 Боты</span><span class="chip">✅ Галочка</span></div>
<button class="btn" onclick="signStart()">Создать аккаунт</button><button class="btn gl" onclick="loginScr()">Войти</button></div>`}
function gbtn(){if(GID&&window.google){setTimeout(()=>{google.accounts.id.initialize({client_id:GID,callback:async r=>{const d=await api('google',{credential:r.credential});d.error?($('#e').textContent=d.error):d.need2fa?code2():boot()}});
 google.accounts.id.renderButton($('#g'),{theme:'filled_blue',size:'large',shape:'pill',width:300,text:'continue_with'})},150);return '<div id="g" style="display:flex;justify-content:center"></div>'}
 return `<button class="btn gl" onclick="$('#e').textContent='Вставь Google Client ID в начале файла'"><b style="color:#5b8cff">G</b>&nbsp; Продолжить с Google</button>`}
const bk=f=>`<button class="back" onclick="${f}">${ic('back')}</button>`;
function signStart(){R={};signPhone()}
async function signPhone(){const d=await api('phones');const sysg=(d.groups||[]).find(g=>g.sys);const free=sysg?sysg.items:[];
 A.innerHTML=`${blobs}<div class="center">${bk('welcome()')}${steps(1)}<div class="logo" style="width:80px;height:80px;border-radius:26px">${ic('phone',38)}</div><h1 style="text-align:center">Твой номер</h1><p class="sub">Введи номер телефона, чтобы создать аккаунт</p>
<div class="glass"><input id="ph" type="tel" placeholder="${free[0]||'+999'}" value="${esc(R.phone||'')}" style="text-align:center;font-size:24px;font-weight:700">${free.length?`<div class="hint" style="text-align:center">⭐ Свободные системные номера — без кода:</div><div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap">${free.map(p=>`<button class="chip" style="border:0;cursor:pointer;color:var(--ac)" onclick="pickPhone('${p}','ph')">${p}</button>`).join('')}</div>`:'<div class="hint" style="text-align:center">Все системные номера заняты</div>'}<button class="lnk" onclick="phonesSheet('ph')">📋 Все свободные номера</button><div class="err" id="e"></div><button class="btn" onclick="doPhone()">Далее</button></div></div>`}
async function phonesSheet(inp){const d=await api('phones');
 const s=sheet(`<header style="background:none"><h2>Свободные номера</h2></header><div class="pad"><p class="note">Выбери номер — он подставится. Для обычных номеров придёт код из SMS, системные — без кода. Занятые не показываются.</p>${(d.groups||[]).map(g=>`<div class="gt" style="margin:14px 0 8px">${g.fl} ${esc(g.n)}</div><div style="display:flex;flex-wrap:wrap;gap:8px">${g.items.map(p=>`<button class="btn gl sm" onclick="pickPhone('${p}','${inp}')">${p}</button>`).join('')}</div>`).join('')}${(d.groups||[]).length?'':'<div class="empty">Свободных номеров нет</div>'}</div>`);
 window._ps=s}
function pickPhone(p,inp){const el=document.getElementById(inp);if(el)el.value=p;R.phone=p;if(window._ps){window._ps.remove();window._ps=null}}
async function doPhone(){const p=$('#ph').value.trim();if(!p){$('#e').textContent='Введи номер';return}
 const d=await api('phone/check',{phone:p});if(d.error){$('#e').textContent=d.error;return}
 R.phone=p;d.need_code?signCode():signProfile()}
function signCode(){A.innerHTML=`${blobs}<div class="center">${bk('signPhone()')}${steps(2)}<div class="logo" style="width:80px;height:80px;border-radius:26px">${ic('lock',38)}</div><h1 style="text-align:center">Код из SMS</h1><p class="sub">Введи код для номера<br><b>${esc(R.phone)}</b></p>
<div class="glass"><input id="cd" type="tel" placeholder="•••••" style="text-align:center;font-size:28px;font-weight:700;letter-spacing:8px"><div class="err" id="e"></div><button class="btn" onclick="doCode()">Подтвердить</button></div></div>`}
async function doCode(){const d=await api('phone/verify',{code:$('#cd').value});if(d.error){$('#e').textContent=d.error;return}signProfile()}
let _nc;function nickChk(){const v=$('#nk').value.trim().replace(/^@/,''),h=$('#nh');clearTimeout(_nc);if(!v){h.textContent='';return}_nc=setTimeout(async()=>{const d=await api('nick/check?n='+encodeURIComponent(v));const e=$('#nh');if(e){e.textContent=d.msg||'';e.style.color=d.ok?'var(--ok)':'var(--bad)'}},350)}
function signProfile(){A.innerHTML=`${blobs}<div class="center">${bk('signPhone()')}${steps(3)}<div class="apick" id="ap" onclick="pickAv()">${R.av?`<img src="${R.av}">`:ic('camera',30)+'Фото'}</div><div class="glass"><input id="nk" placeholder="Ник (@username)" autocapitalize="off" value="${esc(R.nick||'')}" oninput="nickChk()"><div class="hint" id="nh"></div><input id="nm" placeholder="Имя" value="${esc(R.name||'')}">${pwi('pw','Пароль (мин. 6)')}<div class="sbar"><i id="pm"></i></div><div class="err" id="e"></div><button class="btn" onclick="doReg()">Создать аккаунт</button></div></div>`;
 $('#pw').oninput=pwMeter;if(R.nick)nickChk()}
function pickAv(){pick(d=>{R.av=d;$('#ap').innerHTML=`<img src="${d}">`})}
async function doReg(){R.nick=$('#nk').value;R.name=$('#nm').value;const d=await api('register',{nick:R.nick.replace(/^@/,''),name:R.name,password:$('#pw').value,avatar:R.av});if(d.error){$('#e').textContent=d.error;return}boot()}
function loginScr(){A.innerHTML=`${blobs}<div class="center">${bk('welcome()')}<div class="logo" style="width:80px;height:80px;border-radius:26px">${ic('user',38)}</div><h1 style="text-align:center">С возвращением</h1><p class="sub">Войди в свой аккаунт Nova</p><div class="glass"><input id="nk" placeholder="Ник или номер телефона" autocapitalize="off">${pwi('pw','Пароль')}<div class="err" id="e"></div><button class="btn" onclick="doLogin()">Войти</button><button class="btn gl" onclick="phLoginScr()">📱 Войти по номеру (код в чат)</button>${gbtn()}<div style="display:flex;justify-content:space-between"><button class="lnk" onclick="keyScr()">🔑 Войти по ключу</button><button class="lnk" onclick="recScr()">Забыл пароль?</button></div></div></div>`;$('#pw').onkeydown=e=>{if(e.key=='Enter')doLogin()}}
async function doLogin(){const d=await api('login',{nick:$('#nk').value,password:$('#pw').value});if(d.error){$('#e').textContent=d.error;return}if(d.restored)RESTORED=1;d.need2fa?code2():boot()}
/* 📱 вход по номеру: код приходит сообщением в аккаунт (чат Nova Support) */
function phLoginScr(){A.innerHTML=`${blobs}<div class="center">${bk('loginScr()')}<div class="logo" style="width:80px;height:80px;border-radius:26px">${ic('phone',38)}</div><h1 style="text-align:center">Вход по номеру</h1><p class="sub">Введи номер своего аккаунта. Код придёт сообщением в твой аккаунт Nova (чат Nova Support) — открой его на другом устройстве.</p><div class="glass"><input id="ph" type="tel" placeholder="+999" style="text-align:center;font-size:24px;font-weight:700"><div class="err" id="e"></div><button class="btn" onclick="doPhLogin()">Получить код</button></div></div>`}
async function doPhLogin(){const p=$('#ph').value.trim();if(!p){$('#e').textContent='Введи номер';return}const d=await api('login/phone',{phone:p});if(d.error){$('#e').textContent=d.error;return}d.system?phPass(p):phCode(p)}
function phPass(p){A.innerHTML=`${blobs}<div class="center">${bk('phLoginScr()')}<div class="logo" style="width:80px;height:80px;border-radius:26px">${ic('lock',38)}</div><h1 style="text-align:center">Пароль</h1><p class="sub">${esc(p)} — системный номер без кода. Войди по паролю аккаунта.</p><div class="glass">${pwi('pw','Пароль')}<div class="err" id="e"></div><button class="btn" id="pb">Войти</button></div></div>`;
 $('#pb').onclick=async()=>{const d=await api('login',{nick:p,password:$('#pw').value});if(d.error){$('#e').textContent=d.error;return}if(d.restored)RESTORED=1;d.need2fa?code2():boot()}}
function phCode(p){A.innerHTML=`${blobs}<div class="center">${bk('phLoginScr()')}<div class="logo" style="width:80px;height:80px;border-radius:26px">${ic('msg',38)}</div><h1 style="text-align:center">Код отправлен</h1><p class="sub">Мы отправили код сообщением в аккаунт номера <b>${esc(p)}</b> — посмотри чат Nova Support.</p><div class="glass"><input id="cd" type="tel" placeholder="•••••" style="text-align:center;font-size:28px;font-weight:700;letter-spacing:8px"><div class="err" id="e"></div><button class="btn" id="pb">Войти</button><button class="lnk" id="pr">Отправить код ещё раз</button></div></div>`;
 $('#pb').onclick=async()=>{const d=await api('login/phone/confirm',{phone:p,code:$('#cd').value});if(d.error){$('#e').textContent=d.error;return}if(d.restored)RESTORED=1;d.need2fa?code2():boot()};
 $('#pr').onclick=async()=>{const d=await api('login/phone',{phone:p});$('#e').style.color=d.error?'var(--bad)':'var(--ok)';$('#e').textContent=d.error||'Код отправлен ещё раз'}}
function code2(){A.innerHTML=`${blobs}<div class="center">${bk('loginScr()')}<div class="logo" style="width:80px;height:80px;border-radius:26px">${ic('shield',38)}</div><h1 style="text-align:center">Двухэтапная защита</h1><p class="sub">Введи код из приложения-аутентификатора</p><div class="glass"><input id="cd" type="tel" placeholder="••••••" style="text-align:center;font-size:28px;font-weight:700;letter-spacing:8px"><div class="err" id="e"></div><button class="btn" onclick="doCode2()">Войти</button></div></div>`}
async function doCode2(){const d=await api('login2',{code:$('#cd').value});if(d.error){$('#e').textContent=d.error;return}if(d.restored)RESTORED=1;boot()}
function keyScr(){A.innerHTML=`${blobs}<div class="center">${bk('loginScr()')}<div class="logo" style="width:80px;height:80px;border-radius:26px">${ic('key',38)}</div><h1 style="text-align:center">Вход по ключу</h1><div class="glass"><input id="nk" placeholder="Ник или номер" autocapitalize="off"><input id="ky" placeholder="XXXX-XXXX-XXXX-XXXX" autocapitalize="characters"><div class="err" id="e"></div><button class="btn" onclick="doKey()">Войти</button></div></div>`}
async function doKey(){const d=await api('loginkey',{nick:$('#nk').value,key:$('#ky').value});if(d.error){$('#e').textContent=d.error;return}if(d.restored)RESTORED=1;d.need2fa?code2():boot()}
function recScr(){A.innerHTML=`${blobs}<div class="center">${bk('loginScr()')}<div class="logo" style="width:80px;height:80px;border-radius:26px">${ic('mail',38)}</div><h1 style="text-align:center">Восстановление</h1><p class="sub">Введи ник или почту. Код придёт на подтверждённую почту.</p><div class="glass"><input id="nk" placeholder="Ник или почта" autocapitalize="off"><div class="err" id="e"></div><button class="btn" onclick="doRec()">Отправить код</button></div></div>`}
async function doRec(){const d=await api('recover',{nick:$('#nk').value});if(d.error){$('#e').textContent=d.error;return}recScr2(d.nick,d.mask)}
function recScr2(n,m){A.innerHTML=`${blobs}<div class="center">${bk('recScr()')}<h1 style="text-align:center">Новый пароль</h1><p class="sub">Код отправлен на ${esc(m)}</p><div class="glass"><input id="cd" type="tel" placeholder="Код из письма">${pwi('pw','Новый пароль (мин. 6)')}<div class="sbar"><i id="pm"></i></div><div class="err" id="e"></div><button class="btn" onclick="doRec2('${esc(n)}')">Сменить пароль</button></div></div>`;$('#pw').oninput=pwMeter}
async function doRec2(n){const d=await api('recover/confirm',{nick:n,code:$('#cd').value,password:$('#pw').value});if(d.error){$('#e').textContent=d.error;return}loginScr()}

/* ───── ОБЩЕЕ ───── */
const call=async(p,b)=>(await api(p,b)).error;
let MS='',MSG={},BARK='',ET='',_d;
const hd=(t,x='')=>`<header><h2>${t}</h2>${x}<span class="coins">★ ${ME.stars}</span></header>`;
const tm=ts=>{const d=new Date(ts*1000);return d.toDateString()==new Date().toDateString()?hm(ts):d.toLocaleDateString([],{day:'2-digit',month:'2-digit'})};
const li=(t,a)=>`<div class="li" data-a="${a}"><span class="t"><span>${t}</span></span></div>`;
const dbs=f=>()=>{clearTimeout(_d);_d=setTimeout(f,300)};
const closeAll=()=>document.querySelectorAll('.sheet').forEach(x=>x.remove());
function toast(t){const e=document.createElement('div');e.style.cssText='position:absolute;left:50%;top:70px;transform:translateX(-50%);background:var(--card2);color:var(--tx);padding:10px 18px;border-radius:16px;z-index:50;font-weight:700;max-width:80%;text-align:center;box-shadow:0 8px 28px #0006';e.textContent=t;A.appendChild(e);setTimeout(()=>e.remove(),2800)}
function burst(e){const b=document.createElement('div');b.className='burst';b.textContent=e;A.appendChild(b);setTimeout(()=>b.remove(),1500)}
function form(title,note,fields,btn,fn){const s=sheet(`<div class="pad"><h2 style="font-size:20px;margin:6px 0 8px">${title}</h2>${note?`<p class="note">${note}</p>`:''}${fields.map(f=>`<input id="f_${f[0]}" type="${f[2]||'text'}" placeholder="${f[1]}" value="${esc(f[3]||'')}" autocapitalize="off" style="margin-bottom:10px">`).join('')}<div class="err" id="fe"></div><button class="btn" id="fb">${btn}</button></div>`);
 s.querySelector('#fb').onclick=async()=>{const v={};fields.forEach(f=>v[f[0]]=s.querySelector('#f_'+f[0]).value);const r=await fn(v,s);if(r)s.querySelector('#fe').textContent=r;else{s.remove();if(ME)(curPeer?pull(true):draw())}};return s}
const uRow=p=>`<div class="row" onclick="openChat(${p.id})">${ava(p,40)}<div class="t"><b>${vf(p)}${esc(p.name)}${bd(p)}</b><small>@${esc(p.nick)}</small></div></div>`;
function rankInfo(id,l,e){if(e)e.stopPropagation();const cur=Math.max(1,Math.min(l||1,RN.length));
 sheet(`<div class="pad"><div style="text-align:center;margin-bottom:12px"><div style="font-size:0">${rk(cur,92,null)}</div><h2 style="font-size:20px;margin:12px 0 4px">${RN[cur-1]}</h2><p class="note" style="margin:0">Ранг ${cur} из ${RN.length}. Очки дают NFT-рулетка и NFT-юзернеймы.</p></div>${LVT.map((t,i)=>`<div class="rkl ${i+1==cur?'cur':''}">${rk(i+1,38,null)}<div><b>${RN[i]}</b><small>от ${t} очков</small></div></div>`).join('')}</div>`)}
async function devInfo(){try{const h=await navigator.userAgentData.getHighEntropyValues(['model']);if(h.model)api('devices/info',{model:h.model})}catch(e){}}
/* ❄️ баннер замороженного аккаунта */
const fzBar=()=>ME&&ME.frozen?`<div class="fzb" onclick="openChat(${SB})"><i class="snowl">❄</i><i class="snowl s2">❅</i><em>❄️</em><span><b>Аккаунт заморожен</b>${ME.frz_why?'Причина: '+esc(ME.frz_why)+'. ':''}${ME.appeal_left?'⏳ Апелляция на рассмотрении…':'Нажми, напиши в @SpamBot_Info почему аккаунт нужно разблокировать и отправь /appeal.'}</span></div>`:'';
function fzCard(){const fl=Array.from({length:9},(_,i)=>`<span class="fl2" style="left:${6+i*11}%;font-size:${12+i%3*5}px;animation-duration:${5+i%4*2}s;animation-delay:${-i*1.3}s">${i%2?'❄':'❅'}</span>`).join('');
 return `<div class="fzc">${fl}<div class="fi">❄️</div><h2>Чат недоступен</h2><p>Данный чат недоступен из-за нарушения правил сообщества NovaGram. Доступ к сообщениям ограничен.</p><span class="fb">Заблокировано модератором</span></div>`}
function imgView(id,e){if(e)e.stopPropagation();const v=document.createElement('div');v.className='viewer';v.innerHTML=`<img src="/img/${id}"><button>✕</button>`;v.onclick=()=>v.remove();A.appendChild(v)}

/* ───── ГЛАВНАЯ ───── */
function main(){stop();curPeer=null;SQ='';A.innerHTML=`${fzBar()}<div class="view" id="v"></div><nav>${[['chats','chat','Чаты'],['gifts','gift','Подарки'],['set','sliders','Настройки'],['me','user','Профиль']].map(t=>`<a class="${tab==t[0]?'on':''}" onclick="go('${t[0]}')">${ic(t[1],22)}<span>${t[2]}</span></a>`).join('')}</nav>`;draw()}
function go(t){tab=t;main()}
async function draw(){stop();await refreshMe();if(!ME||!$('#v'))return;({chats:vChats,gifts:vGifts,set:vSet,me:vMe}[tab])()}

/* ───── ЧАТЫ ───── */
const dr=id=>{try{return localStorage['nd'+id]||''}catch(e){return''}};
const tkS=r=>`<svg class="tk ${r?'r':''}" width="${r?18:14}" height="11" viewBox="0 0 18 11" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M1.5 5.8l3.2 3.2L11 1.8"/>${r?'<path d="M6.5 8.7l.5.5L15.5 1.8"/>':''}</svg>`;
const rowH=p=>{const d=dr(p.id),last=d?`<span style="color:var(--bad)">Черновик: </span>${esc(d)}`:(p.mine?`<span style="color:${p.rd?'var(--ac)':'var(--mut)'}">${tkS(p.rd)}</span> `:'')+esc(p.last||p.bio||'');
 return `<div class="row" onclick="openChat(${p.id})">${avd(p,54)}<div class="t"><b>${p.pin?'📌 ':''}${vf(p)}${esc(nameOf(p))}${bd(p)}${p.mute?' 🔕':''}</b><small>${last}</small></div><div class="rt"><span class="tm">${p.ts?tm(p.ts):''}</span>${p.un?`<span class="ub ${p.mute?'mu':''}">${p.un}</span>`:''}</div></div>`};
const flt=p=>FT=='arch'?!!p.arch:(!p.arch&&(FT=='all'||(FT=='dm'&&p.id>0&&!p.bot)||(FT=='grp'&&p.id<0)||(FT=='bot'&&p.bot)||(FT=='un'&&p.un)));
function vChats(){const v=$('#v');v.innerHTML=hd('Чаты',`<button class="ib go" onclick="newGroup()">${ic('edit',20)}</button>`)+`<div class="pad" style="padding-bottom:6px"><input id="sq" placeholder="🔍 Поиск людей, ботов, групп" autocapitalize="off"></div><div class="tabs" id="tb">${[['all','Все'],['dm','Личные'],['grp','Группы'],['bot','Боты'],['un','Непрочитанные'],['arch','📥 Архив']].map(t=>`<button data-t="${t[0]}" class="${FT==t[0]?'on':''}">${t[1]}</button>`).join('')}</div><div id="cl"></div>`;
 $('#sq').oninput=dbs(search);$('#tb').onclick=e=>{const b=e.target.closest('[data-t]');if(!b)return;FT=b.dataset.t;$('#tb').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x==b));paintCl()};load();timer=setInterval(()=>{const s=$('#sq');if(s&&!s.value)load()},4000)}
function paintCl(){const c=$('#cl');if(c)c.innerHTML=CH.filter(flt).map(rowH).join('')||`<div class="empty">${FT=='arch'?'Архив пуст.<br>Отправь чат в архив через меню ⋮ в чате':'Здесь пока пусто'}</div>`}
async function load(){const d=await api('chats');if(!$('#cl')||!d.chats)return;CH=d.chats;paintCl()}
async function search(){const s=$('#sq');if(!s)return;const t=s.value.trim();if(!t)return load();const d=await api('users?q='+encodeURIComponent(t));const c=$('#cl');if(c&&s.value.trim()==t)c.innerHTML=[...(d.groups||[]),...(d.users||[])].map(rowH).join('')||'<div class="empty">Ничего не найдено</div>'}
function newGroup(){const s=sheet(`<div class="pad"><h2 style="font-size:20px;margin:6px 0 12px">Новый чат</h2><input id="gt" placeholder="Название" style="margin-bottom:10px"><div class="err" id="fe"></div><button class="btn" data-k="group">👥 Создать группу</button><button class="btn gl" style="margin-top:10px" data-k="channel">📢 Создать канал</button></div>`);
 s.querySelectorAll('[data-k]').forEach(b=>b.onclick=async()=>{const d=await api('group/create',{title:s.querySelector('#gt').value,kind:b.dataset.k});if(d.error)s.querySelector('#fe').textContent=d.error;else openChat(d.id)})}

/* ───── ФОН ЧАТА ───── */
const BGS=[['Nova',''],['Закат','linear-gradient(160deg,#ff9a8b,#ff6a88 45%,#7a56ff)'],['Океан','linear-gradient(160deg,#0f2b5b,#1b6ca8 60%,#3bd4ff)'],['Лес','linear-gradient(160deg,#0d3b2e,#1f7a56 60%,#9be15d)'],['Ночь','radial-gradient(circle at 30% 20%,#2b2f6b,#0a0c1e 70%)'],['Сакура','linear-gradient(160deg,#ffdce8,#ffb3d1 60%,#e58bff)']];
const bgv=()=>{try{return +localStorage.nova_bg||0}catch(e){return 0}};
function applyBg(){const m=$('#ms'),b=BGS[bgv()];if(!m)return;if(b&&b[1]){m.classList.add('cb');m.style.setProperty('--cbg',b[1])}else m.classList.remove('cb')}
function setBgSheet(){const s=sheet(`<div class="pad"><h2 style="font-size:20px;margin:6px 0 12px">Фон чата</h2><div class="bgp">${BGS.map((b,i)=>`<div data-b="${i}" class="${bgv()==i?'on':''}" style="background:${b[1]||'radial-gradient(circle at 10% 0,#5b8cff55,transparent 55%),radial-gradient(circle at 95% 100%,#9b5cff55,transparent 55%),#0f1526'}">${b[0]}</div>`).join('')}</div></div>`);
 s.querySelectorAll('[data-b]').forEach(e=>e.onclick=()=>{try{localStorage.nova_bg=e.dataset.b}catch(_){}s.remove();toast('Фон изменён')})}

/* ───── ОКНО ЧАТА ───── */
function openChat(pid){stop();curPeer=pid;REPLY=null;EDIT=0;MS='';BARK='';PEER=null;TYP=[];NEWC=0;PLEN=0;SQ='';PIN=null;LD=null;
 A.innerHTML=`${fzBar()}<header class="ch"><button class="back" onclick="main()">${ic('back')}</button><div class="row" style="padding:0;flex:1;min-width:0" onclick="peerInfo()"><span id="ca"></span><div class="t"><b id="cn"></b><small id="cs"></small></div></div><button class="ib" onclick="chatMenu()">${ic('more')}</button></header><div id="srch"></div><div id="pn"></div><div class="msgs" id="ms" onscroll="onScr()"></div><button class="fab" id="fab" onclick="toBot()">${ic('down',22)}<i id="fbn"></i></button><div class="chips" id="ch"></div><div class="rp" id="rp"></div><div id="bar"></div>`;
 applyBg();pull(true);timer=setInterval(()=>pull(false),1500)}
const nearBot=()=>{const m=$('#ms');return !m||m.scrollHeight-m.scrollTop-m.clientHeight<140};
function onScr(){const f=$('#fab');if(!f)return;const n=nearBot();f.style.display=n?'none':'flex';if(n){NEWC=0;$('#fbn').style.display='none'}}
function toBot(){const m=$('#ms');m.scrollTo({top:m.scrollHeight,behavior:'smooth'});NEWC=0}
const bigE=t=>t&&t.length<16&&/^(\p{Extended_Pictographic}|\u200d|\ufe0f|\s){1,6}$/u.test(t);
function renderMsgs(d){let last='',h='';const L=SQ?d.msgs.filter(x=>(x.text||'').toLowerCase().includes(SQ)):d.msgs;
 const sm=(a,b)=>a&&b&&new Date(a.ts*1000).toDateString()==new Date(b.ts*1000).toDateString()&&a.mine==b.mine&&(a.wid||0)==(b.wid||0)&&Math.abs(b.ts-a.ts)<180&&!a.gift&&!b.gift;
 L.forEach((x,i)=>{const k=new Date(x.ts*1000).toDateString();if(k!=last){last=k;h+=`<div class="dsp"><span>${dayLbl(x.ts)}</span></div>`}h+=msgH(x,d,sm(L[i-1],x)&&k==new Date(L[i-1].ts*1000).toDateString(),sm(x,L[i+1]))});
 return h||(SQ?'<div class="empty">🔍 Ничего не найдено</div>':'<div class="empty">Напиши первое сообщение 👋</div>')}
const canPin=()=>PEER&&((PEER.id>0&&!PEER.gone&&!PEER.frozen)||(PEER.id<0&&(PEER.role=='owner'||PEER.role=='admin')));
function pinBar(){const e=$('#pn');if(!e)return;e.innerHTML=PIN&&!(PEER&&PEER.gone)?`<div class="pnb" onclick="jumpPin()"><span>📌</span><div><b>Закреплённое сообщение</b>${esc(PIN.t)}</div>${canPin()?'<button onclick="unpinX(event)">✕</button>':''}</div>`:''}
function jumpPin(){if(!PIN)return;const el=document.getElementById('m'+PIN.id);if(!el)return toast('Сообщение выше в истории');el.scrollIntoView({behavior:'smooth',block:'center'});el.classList.add('hl');setTimeout(()=>el.classList.remove('hl'),1500)}
async function unpinX(e){e.stopPropagation();const r=await api('msg/pin',{id:PIN.id,off:true});if(r.error)toast(r.error);pull(true)}
function rerender(){if(!LD)return;const m=$('#ms');if(m)m.innerHTML=renderMsgs(LD)}
function chatSearch(){const b=$('#srch');if(!b)return;b.innerHTML=`<div class="bar" style="padding:8px 12px"><input id="si" placeholder="🔍 Поиск по чату"><button class="ib" onclick="closeSearch()">✕</button></div>`;const i=$('#si');i.focus();i.oninput=()=>{SQ=i.value.trim().toLowerCase();rerender()}}
function closeSearch(){SQ='';const b=$('#srch');if(b)b.innerHTML='';rerender()}
async function pull(first){const pid=curPeer;if(!pid)return;const d=await api('messages/'+pid+'?after=0');if(pid!=curPeer||!$('#ms'))return;
 if(d.error){if(first)$('#ms').innerHTML=`<div class="empty">${esc(d.error)}</div>`;return}
 PEER=d.peer;TYP=d.typing||[];PIN=d.pinned;const sig=JSON.stringify([d.msgs,d.rx,d.pr,d.peer,TYP,d.pinned]);if(sig==MS&&!first)return;MS=sig;LD=d;
 MSG=Object.fromEntries(d.msgs.map(x=>[x.id,x]));head();bar();pinBar();
 const m=$('#ms'),near=nearBot();
 m.innerHTML=PEER.gone&&PEER.id<0?fzCard():renderMsgs(d);
 if(!SQ&&(first||near)){m.scrollTop=m.scrollHeight;NEWC=0}
 else if(!SQ){const add=d.msgs.length-PLEN,l=d.msgs[d.msgs.length-1];if(add>0&&l&&!l.mine&&PLEN){NEWC+=add;const b=$('#fbn');if(b){b.textContent=NEWC;b.style.display='flex'}}}
 PLEN=d.msgs.length;onScr()}
function head(){$('#ca').innerHTML=avd(PEER,42);$('#cn').innerHTML=vf(PEER)+esc(nameOf(PEER))+bd(PEER)+(PEER.mute?' 🔕':'');
 const cs=$('#cs');if(TYP.length){cs.className='on';cs.innerHTML=(PEER.id<0?esc(TYP.join(', '))+' ':'')+'печатает<span class="td"><i></i><i></i><i></i></span>'}else{const t=stx(PEER);cs.className=t=='в сети'?'on':'';cs.textContent=t}
 $('#ch').innerHTML=(PEER.frozen||PEER.gone)&&!isSelf(PEER)?'':(PEER.cmds||[]).map(c=>`<button onclick="sendX({text:'${esc(c)}'})">${esc(c)}</button>`).join('')}
let _tt=0;function typ(){const i=$('#mi');if(!i)return;try{i.value?localStorage['nd'+curPeer]=i.value:localStorage.removeItem('nd'+curPeer)}catch(e){}if(i.value&&!EDIT&&Date.now()-_tt>2500){_tt=Date.now();api('typing',{to:curPeer})}}
function bar(){const k=PEER.joined+'|'+PEER.can_post+'|'+PEER.id+'|'+PEER.frozen+'|'+PEER.gone+'|'+PEER.blk;if(k==BARK)return;BARK=k;const b=$('#bar');
 if(PEER.id<0&&PEER.frozen){b.innerHTML=`<div class="bar"><div class="note" style="flex:1;text-align:center;margin:0">❄️ Чат недоступен</div></div>`;return}
 if(PEER.id>0&&(PEER.frozen||PEER.gone)&&!isSelf(PEER)){b.innerHTML=`<div class="bar"><div class="note" style="flex:1;text-align:center;margin:0">❄️ Этот аккаунт недоступен</div></div>`;return}
 if(PEER.id>0&&PEER.blk){b.innerHTML=`<div class="bar"><button class="btn gl" onclick="toggleBlock()">🚫 Разблокировать</button></div>`;return}
 if(PEER.id<0&&!PEER.joined){b.innerHTML=`<div class="bar"><button class="btn" onclick="joinG()">Вступить</button></div>`;return}
 if(PEER.id<0&&!PEER.can_post){b.innerHTML=`<div class="bar"><button class="ib" onclick="giftSheet()">🎁</button><div class="note" style="flex:1;text-align:center;margin:0">Писать могут только админы</div></div>`;return}
 b.innerHTML=`<div class="bar"><button class="ib" onclick="pickImg()">${ic('image',22)}</button><button class="ib" onclick="stickSheet()">😊</button><button class="ib" onclick="giftSheet()">🎁</button><input id="mi" placeholder="Сообщение" autocomplete="off"><button class="ib go" onclick="sendMsg()">${ic('send',20)}</button></div>`;
 const i=$('#mi');i.value=dr(curPeer);i.oninput=typ;i.onkeydown=e=>{if(e.key=='Enter')sendMsg()}}
function msgH(x,d,cp,cn){const grpc=d.peer.id<0,rx=(d.rx[x.id]||[]).map(r=>`<span class="rx ${r.me?'me':''}" onclick="react(${x.id},'${r.e}',event)">${r.e} ${r.c}</span>`).join('');
 const who=grpc&&!x.mine&&!cp&&x.who?`<b class="wn" style="color:hsl(${(x.wid||1)*67%360} 80% 68%)">${esc(x.who)}</b>`:'';
 const rq=x.rq?`<div class="rq"><b>${esc(x.rq.n)}</b>${esc(x.rq.t)}</div>`:'';
 const fw=x.fwd?`<div class="fw">↪ Переслано от<b>${esc(x.fwd)}</b></div>`:'';
 const chk=x.mine&&d.peer.id>0?tkS(x.id<=d.pr):'';
 const t=`<span class="mt">${x.ed?'изм. ':''}${hm(x.ts)}${chk}</span>`,rr=rx?`<div class="rxs">${rx}</div>`:'';
 const avs=grpc&&!x.mine?`<span class="avs">${cn?'':ava({id:x.wid,name:x.who,av:x.wav,frozen:x.wfz},30)}</span>`:'';
 const R_=(c,inner)=>`<div class="mr ${x.mine?'me':'in'} ${cp?'cp':''}" id="m${x.id}">${avs}<div class="m ${x.mine?'me':'in'} ${cp?'cp':''} ${cn?'cn':''} ${c}" onclick="msgMenu(${x.id})">${inner}</div></div>`;
 if(x.gift)return R_('st',`${who}<div class="gm">${x.gift.e}<i>${x.mine?'Вы подарили':'Вам подарили'}: ${esc(x.gift.n)}</i></div>${rr}`);
 if(x.sticker)return R_('st',`${who}${rq}<div class="gm">${x.sticker}</div>${rr}`);
 const im=x.img?`<img class="mi" src="/img/${x.id}" loading="lazy" onclick="imgView(${x.id},event)">`:'';
 const big=!x.img&&!x.rq&&!x.fwd&&bigE(x.text);
 return R_(big?'big':'',`${who}${fw}${rq}${im}${x.text?lk(esc(x.text)):''}${rr}${t}`)}
async function react(id,e,ev){if(ev)ev.stopPropagation();await api('react',{id,e});pull(true)}
function showRp(){const r=$('#rp');if(!r)return;const o=EDIT?{n:'Редактирование',t:ET}:REPLY?{n:'Ответ: '+REPLY.n,t:REPLY.t}:null;r.innerHTML=o?`<div><b>${esc(o.n)}</b>${esc(o.t)}</div><button onclick="cancelRp(1)">✕</button>`:''}
function cancelRp(clr){REPLY=null;if(EDIT&&clr){const i=$('#mi');if(i)i.value=dr(curPeer)}EDIT=0;showRp()}
function msgMenu(id){const x=MSG[id];if(!x||!PEER)return;const post=!(PEER.id<0&&!PEER.can_post)&&!PEER.frozen&&!PEER.gone&&!PEER.blk,adm=PEER.role=='owner'||PEER.role=='admin',isP=PIN&&PIN.id==id;
 const s=sheet(`<div class="pad"><div class="rrow">${RE.map(e=>`<button data-e="${e}">${e}</button>`).join('')}</div><div class="grp" style="margin:0">${post?li('↩️ Ответить','r'):''}${!x.gift?li('↪️ Переслать','f'):''}${x.text?li('📋 Копировать','c'):''}${canPin()&&!x.gift?li(isP?'📌 Открепить':'📌 Закрепить','pn'):''}${x.mine&&x.text&&!x.gift&&!x.sticker?li('✏️ Изменить','e'):''}${!x.gift&&(x.mine||adm)?li('🗑 Удалить','d'):''}</div></div>`);
 s.querySelectorAll('[data-e]').forEach(b=>b.onclick=async()=>{s.remove();await api('react',{id,e:b.dataset.e});pull(true)});
 s.querySelectorAll('[data-a]').forEach(e=>e.onclick=async()=>{const a=e.dataset.a;s.remove();
  if(a=='r'){EDIT=0;REPLY={id,n:x.mine?'Вы':(x.who||nameOf(PEER)),t:x.text||(x.img?'📷 Фото':x.sticker?'Стикер '+x.sticker:x.gift?'🎁 '+x.gift.n:'')};showRp();const i=$('#mi');if(i)i.focus()}
  else if(a=='f')fwdSheet(id);
  else if(a=='c'){try{navigator.clipboard.writeText(x.text)}catch(_){}toast('Скопировано')}
  else if(a=='pn'){const r=await api('msg/pin',{id,off:isP});if(r.error)toast(r.error);else toast(isP?'Откреплено':'📌 Закреплено');pull(true)}
  else if(a=='e'){REPLY=null;EDIT=id;ET=x.text;const i=$('#mi');if(i){i.value=x.text;i.focus()}showRp()}
  else if(a=='d'){await api('msg/delete',{id});pull(true)}})}
async function fwdSheet(id){const d=await api('chats');const L=(d.chats||[]).filter(p=>!(p.frozen||p.gone)||isSelf(p));
 const s=sheet(`<div style="padding-bottom:6px"><h2 style="font-size:20px;padding:6px 18px">Переслать в…</h2>${L.map(p=>`<div class="row" data-p="${p.id}">${avOf(p,42)}<div class="t"><b>${esc(nameOf(p))}</b><small>${esc(stx(p)||'')}</small></div></div>`).join('')}</div>`);
 s.querySelectorAll('[data-p]').forEach(e=>e.onclick=async()=>{const r=await api('forward',{id,to:+e.dataset.p});s.remove();toast(r.error||'Переслано ↪️');if(!r.error&&+e.dataset.p==curPeer)pull(true)})}
async function sendMsg(){const i=$('#mi');if(!i)return;const t=i.value.trim();if(!t)return;i.value='';
 if(EDIT){const d=await api('msg/edit',{id:EDIT,text:t});cancelRp();if(d.error)toast(d.error);return pull(true)}
 try{localStorage.removeItem('nd'+curPeer)}catch(e){}
 const d=await api('send',{to:curPeer,text:t,reply:REPLY?REPLY.id:undefined});cancelRp();if(d.error)toast(d.error);await pull(true);toBot()}
async function sendX(o){const d=await api('send',Object.assign({to:curPeer,reply:REPLY?REPLY.id:undefined},o));cancelRp();if(d.error){toast(d.error);return false}await pull(true);toBot();return true}
/* 🖼 фото из галереи */
function pickImg(){const f=document.createElement('input');f.type='file';f.accept='image/*';
 f.onchange=()=>{const fl=f.files[0];if(!fl)return;const r=new FileReader();r.onload=()=>{const im=new Image();
  im.onload=()=>{const k=Math.min(1,1280/Math.max(im.width,im.height)),c=document.createElement('canvas');c.width=Math.max(1,Math.round(im.width*k));c.height=Math.max(1,Math.round(im.height*k));
   const x=c.getContext('2d');x.fillStyle='#fff';x.fillRect(0,0,c.width,c.height);x.drawImage(im,0,0,c.width,c.height);imgPreview(c.toDataURL('image/jpeg',.82))};
  im.onerror=()=>toast('Не удалось открыть картинку');im.src=r.result};r.readAsDataURL(fl)};f.click()}
function imgPreview(data){const s=sheet(`<div class="pad"><img class="pv" src="${data}"><input id="icap" placeholder="Подпись (необязательно)" style="margin-bottom:10px"><button class="btn" id="isb">Отправить фото</button></div>`);
 s.querySelector('#isb').onclick=async()=>{const t=s.querySelector('#icap').value.trim();s.remove();await sendX({img:data,text:t})}}
function stickSheet(){const s=sheet(`<div class="pad"><div style="display:grid;grid-template-columns:repeat(6,1fr);gap:6px;font-size:34px;text-align:center">${ST.map(e=>`<span data-s="${e}" style="cursor:pointer">${e}</span>`).join('')}</div></div>`);
 s.querySelectorAll('[data-s]').forEach(e=>e.onclick=()=>{s.remove();sendX({sticker:e.dataset.s})})}
function giftSheet(){const s=sheet(`<div style="padding:0 0 6px"><h2 style="font-size:20px;padding:6px 18px">Отправить подарок</h2><div class="grid">${GIFTS.map(g=>`<div class="gc p" data-g="${g.id}"><div class="e">${g.e}</div><b>${esc(g.n)}</b><small>★ ${g.p}</small></div>`).join('')}</div></div>`);
 s.querySelectorAll('[data-g]').forEach(e=>e.onclick=async()=>{const g=GIFTS.find(x=>x.id==e.dataset.g);s.remove();if(await sendX({gift:g.id})){burst(g.e);refreshMe()}})}
function peerInfo(){if(!PEER)return;if(PEER.id<0){PEER.frozen?toast('❄️ Чат недоступен'):groupInfo(PEER.id)}else showUser(PEER.id)}
function chatMenu(){if(!PEER)return;const dm=PEER.id>0&&!isSelf(PEER)&&!PEER.gone&&!(PEER.bot&&!PEER.cmds);
 const s=sheet(`<div class="pad"><div class="grp" style="margin:0">${li('🔍 Поиск по чату','s')}${li(PEER.pin?'📌 Открепить чат':'📌 Закрепить чат','p')}${li(PEER.mute?'🔔 Включить уведомления':'🔕 Заглушить','m')}${li(PEER.arch?'📤 Вернуть из архива':'📥 В архив','ar')}${li('🧹 Очистить историю','cl')}${li('👤 Профиль','i')}${dm&&!PEER.bot?li(PEER.blk?'✅ Разблокировать':'🚫 Заблокировать','b'):''}</div></div>`);
 s.querySelectorAll('[data-a]').forEach(e=>e.onclick=async()=>{const a=e.dataset.a;s.remove();
  if(a=='s')chatSearch();
  else if(a=='p'){await api('pin',{id:curPeer,off:PEER.pin});pull(true)}
  else if(a=='m'){await api('mute',{id:curPeer,off:PEER.mute});pull(true)}
  else if(a=='ar'){const was=PEER.arch;await api('archive',{id:curPeer,off:was});toast(was?'Возвращено из архива':'📥 Чат в архиве');pull(true)}
  else if(a=='cl')confirmBox('🧹','Очистить историю?','Сообщения исчезнут только у тебя. У собеседника всё останется.','Очистить',async()=>{const r=await api('chat/clear',{id:curPeer});if(r.error)toast(r.error);else toast('История очищена');pull(true)},true);
  else if(a=='i')peerInfo();else if(a=='b')toggleBlock()})}
async function toggleBlock(){const r=await api('block',{id:PEER.id,off:PEER.blk});if(r.error)return toast(r.error);toast(PEER.blk?'Разблокирован':'🚫 Заблокирован');BARK='';pull(true)}
async function joinG(){const d=await api('group/join',{id:-curPeer});if(d.error)toast(d.error);BARK='';pull(true)}

/* ───── ПРОФИЛЬ ЛЮБОГО ПОЛЬЗОВАТЕЛЯ ───── */
const bdayTxt=b=>{if(!b)return'';const t=new Date(),k=String(t.getDate()).padStart(2,'0')+'.'+String(t.getMonth()+1).padStart(2,'0');return k==b?'🎉 Сегодня день рождения!':'🎂 '+b};
async function showUser(uid){const u=await api('user/'+uid);if(u.error)return toast(u.error);
 const gone=u.gone&&!u.self;
 const s=sheet(`<div><div class="cover ${u.bgn?'nf':''}" style="${u.bgn?cvs(u.bgn):''}${gone?'background:linear-gradient(160deg,#6ab8ff,#5b8cff 55%,#9b86ff)':''}">${sides(u.bgn)}<div class="pav">${ava(u,108)}</div><h1>${vf(u,20)}${esc(u.name)}${bd(u)}</h1><p>${gone?'':'@'+esc(u.nick)}</p>${u.nu?`<span class="nuu">💎 @${esc(u.nu)}</span>`:''}${u.bio?`<p>${esc(u.bio)}</p>`:''}${u.bday?`<p style="font-size:13px">${bdayTxt(u.bday)}</p>`:''}<p style="font-size:13px">${esc(u.self?'это ты':seenTxt(u))}</p></div>
 <div class="stats"><div data-l="fl"><b>${u.nfl}</b><span>Подписчики</span></div><div data-l="fg"><b>${u.nfg}</b><span>Подписки</span></div><div><b>${u.gifts}</b><span>Подарки</span></div></div>
 ${gone?'':`<div class="grp" style="padding:12px 16px;display:flex;align-items:center;gap:12px">${rk(u.lvl||1,34,null)}<div><b>${RN[Math.max(0,(u.lvl||1)-1)]}</b><div style="color:var(--mut);font-size:13px">${u.bot?'бот':u.score+' очков рейтинга'}</div></div></div>`}
 <div class="pad" style="padding-top:14px">${u.self||gone?'':`<button class="btn" data-w="1">Написать</button>${u.bot?'':`<button class="btn gl" style="margin-top:10px" data-f="1">${u.me_follow?'Отписаться':'Подписаться'}</button>`}`}${gone?'':`<div class="grp" style="margin:12px 0 0">${li('📋 Скопировать @'+esc(u.nick),'cp')}${u.self||u.bot?'':li(u.blk?'✅ Разблокировать':'🚫 Заблокировать','bl')}</div>`}</div></div>`);
 const w=s.querySelector('[data-w]');if(w)w.onclick=()=>openChat(uid);
 const f=s.querySelector('[data-f]');if(f)f.onclick=async()=>{await api('follow',{id:uid,off:u.me_follow});s.remove();showUser(uid)};
 s.querySelectorAll('[data-a]').forEach(e=>e.onclick=async()=>{if(e.dataset.a=='cp'){try{navigator.clipboard.writeText('@'+u.nick)}catch(_){}toast('Скопировано')}else{const r=await api('block',{id:uid,off:u.blk});toast(r.error||(u.blk?'Разблокирован':'🚫 Заблокирован'));s.remove();if(curPeer==uid){BARK='';pull(true)}}});
 s.querySelectorAll('[data-l]').forEach(e=>e.onclick=()=>{const L=u[e.dataset.l];sheet(`<div class="pad"><div class="grp" style="margin:0">${L.map(uRow).join('')||'<div class="empty">Пусто</div>'}</div></div>`)})}

/* ───── ГРУППЫ И КАНАЛЫ ───── */
async function groupInfo(pid){const d=await api('group/info?id='+(-pid));if(d.error)return toast(d.error);const g=d.info,r=d.role,adm=r=='owner'||r=='admin';
 if(g.frozen)return toast('❄️ Чат недоступен');
 const s=sheet(`<div class="pad"><div style="text-align:center">${ava({id:-pid,name:g.name},84)}<h2 style="font-size:21px;margin-top:10px">${esc(g.name)}${nb(g.nft)}</h2><p class="note" style="margin:4px 0">${esc(g.bio)}</p><p class="note" style="margin:0">${esc(g.desc||'')}</p></div>
 <div class="grp" style="margin:12px 0 0">${adm?li('✏️ Название и описание','e'):''}${r=='owner'?li('@ Юзернейм','u')+li('💎 NFT группы','n')+li('🗑 Удалить','d'):''}${r&&r!='owner'?li('🚪 Выйти','l'):''}</div>
 ${d.gifts.length?`<div class="gt" style="margin:14px 0 6px">Подарки</div><div style="font-size:30px">${d.gifts.slice(0,30).map(x=>x.g.e).join(' ')}</div>`:''}
 <div class="gt" style="margin:14px 0 6px">Участники (${d.members.length})</div><div class="grp" style="margin:0">${d.members.map(m=>`<div class="row" data-m="${m.id}">${ava(m,40)}<div class="t"><b>${vf(m)}${esc(m.name)}${bd(m)}</b><small>${{owner:'владелец ',admin:'админ '}[m.role]||''}@${esc(m.nick)}</small></div></div>`).join('')}</div></div>`);
 s.querySelectorAll('[data-m]').forEach(e=>e.onclick=()=>memberMenu(pid,r,d.members.find(m=>m.id==e.dataset.m)));
 s.querySelectorAll('[data-a]').forEach(e=>e.onclick=()=>({
  e:()=>form('Группа','',[['t','Название','text',g.name],['d','Описание','text',g.desc||'']],'Сохранить',v=>call('group/edit',{id:-pid,title:v.t,desc:v.d})),
  u:()=>form('Юзернейм группы','Пусто — убрать юзернейм.',[['n','Юзернейм','text',g.uname||'']],'Сохранить',v=>call('group/uname',{id:-pid,name:v.n})),
  n:()=>grpNft(pid),
  d:()=>confirmBox('🗑','Удалить?','Чат и все сообщения исчезнут навсегда.','Удалить',async()=>{await api('group/delete',{id:-pid});main()},true),
  l:()=>confirmBox('🚪','Выйти из чата?','Ты сможешь вступить снова.','Выйти',async()=>{await api('group/leave',{id:-pid});main()})})[e.dataset.a]())}
function memberMenu(pid,r,m){const own=r=='owner',can=m.role!='owner'&&m.id!=ME.id&&(own||(r=='admin'&&m.role=='member'));
 const s=sheet(`<div class="pad"><div class="grp" style="margin:0">${li('👤 Профиль','p')}${own&&m.role!='owner'?li(m.role=='admin'?'🛡 Снять админа':'🛡 Сделать админом','a')+li('👑 Передать владение','t'):''}${can?li('🚫 Удалить из группы','k'):''}</div></div>`);
 const run=async(p,b)=>{const d=await api(p,b);if(d.error)toast(d.error);closeAll();pull(true);groupInfo(pid)};
 s.querySelectorAll('[data-a]').forEach(e=>e.onclick=()=>({p:()=>showUser(m.id),a:()=>run('group/admin',{id:-pid,uid:m.id,on:m.role!='admin'}),t:()=>run('group/transfer',{id:-pid,uid:m.id}),k:()=>run('group/kick',{id:-pid,uid:m.id})})[e.dataset.a]())}
async function grpNft(pid){const d=await api('nft');const s=sheet(`<div class="pad"><h2 style="font-size:20px;margin:6px 0 10px">NFT группы</h2><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px">${d.items.map(i=>`<div data-i="${i.id}" style="text-align:center;cursor:pointer">${nftCard(i.kind,i.anim,'sm')}</div>`).join('')||'<div class="empty" style="grid-column:1/4">У тебя нет NFT</div>'}</div><button class="btn gl" style="margin-top:12px" data-i="0">Снять NFT</button></div>`);
 s.querySelectorAll('[data-i]').forEach(e=>e.onclick=async()=>{const r=await api('group/nft',{id:-pid,nft:+e.dataset.i});if(r.error)toast(r.error);closeAll();pull(true)})}

/* ───── ПОДАРКИ / NFT ───── */
async function vGifts(){const v=$('#v');const n=await api('nft'),g=await api('mygifts');if(!$('#v'))return;
 v.innerHTML=hd('Подарки')+`<div class="pad"><button class="btn" onclick="bonus()">🎁 Ежедневный бонус +20 ★</button>
 <div class="spin"><h2 style="font-size:18px">NFT-рулетка</h2><p class="note">${SP} ★ за прокрутку: выпадает NFT и очки ранга</p><div class="reel"><div class="strip" id="st"></div><div class="mark"></div></div><button class="btn" id="spb" onclick="spin()">Крутить за ${SP} ★</button></div>
 <div class="gt" style="margin:18px 0 8px">Мои NFT (${n.items.length})</div><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px">${n.items.map(i=>`<div onclick="nftMenu(${i.id},'${i.kind}','${i.anim}',${i.eq},${i.bg})" style="text-align:center;cursor:pointer">${nftCard(i.kind,i.anim,'sm')}<small style="color:var(--mut)">${nm(i.kind).n}${i.eq?' ✓':''}${i.bg?' ▦':''}</small></div>`).join('')||'<div class="empty" style="grid-column:1/4">Пока нет NFT</div>'}</div>
 <div class="gt" style="margin:18px 0 8px">Полученные подарки</div><div class="grid" style="padding:0">${g.items.map(x=>`<div class="gc"><div class="e">${x.g.e}</div><b>${esc(x.g.n)}</b><small>от ${esc(x.frm)}</small></div>`).join('')||'<div class="empty" style="grid-column:1/3">Пока нет подарков</div>'}</div></div>`;reelInit()}
const reelH=k=>{const n=nm(k);return `<div class="ri"><div style="--c1a:${n.c[0]}66;--rc:${RC[n.r]||'#fff'}">${art(k)}</div></div>`};
const rndK=()=>NFTS[Math.random()*NFTS.length|0].id;
function reelInit(){const s=$('#st');if(s)s.innerHTML=Array.from({length:12},()=>reelH(rndK())).join('')}
async function bonus(){const d=await api('bonus',{});toast(d.error||'+20 ★ получено!');draw()}
async function spin(){const b=$('#spb');b.disabled=true;const d=await api('nft/spin',{});if(d.error){b.disabled=false;return toast(d.error)}
 const st=$('#st'),W=st.parentElement.clientWidth,T=36;
 st.style.transition='none';st.style.transform='translateX(0)';st.innerHTML=Array.from({length:T+6},(_,i)=>reelH(i==T?d.kind:rndK())).join('');st.offsetWidth;
 st.style.transition='';st.style.transform=`translateX(${W/2-(T*100+50)-(Math.random()*40-20)}px)`;
 setTimeout(async()=>{await refreshMe();const n=nm(d.kind);
  sheet(`<div style="text-align:center;padding:12px 18px 14px">${nftCard(d.kind,'float')}<h2 style="font-size:21px">${n.n}</h2><div style="color:${RC[n.r]};font-weight:800;margin:6px 0">${n.r}</div><p class="note">+${d.pts} очков ранга${d.up?' · 🎉 ранг повышен до '+d.lvl+' — '+RN[d.lvl-1]:''}</p></div>`);
  if(tab=='gifts'&&$('#v'))vGifts()},4400)}
function nftMenu(id,k,a,eq,bg){const n=nm(k);
 const s=sheet(`<div class="pad" style="text-align:center">${nftCard(k,a)}<h2 style="font-size:20px">${n.n}</h2><div style="color:${RC[n.r]};font-weight:800">${n.r}</div><div class="chips" style="justify-content:center;flex-wrap:wrap;background:none">${ANIMS.map(x=>`<button data-an="${x[0]}">${x[1]}</button>`).join('')}</div><button class="btn" data-q="eq">${eq?'Снять с ника':'Надеть рядом с ником'}</button><button class="btn gl" style="margin-top:10px" data-q="bg">${bg?'Убрать узор':'Узор по бокам профиля'}</button></div>`);
 const done=()=>{s.remove();vGifts()};
 s.querySelectorAll('[data-an]').forEach(b=>b.onclick=async()=>{await api('nft/anim',{id,anim:b.dataset.an});done()});
 s.querySelector('[data-q=eq]').onclick=async()=>{await api('nft/equip',{id:eq?0:id});done()};
 s.querySelector('[data-q=bg]').onclick=async()=>{await api('nft/bg',{id:bg?0:id});done()}}

/* ───── НАСТРОЙКИ ───── */
function vSet(){const v=$('#v');const it=(c,i,t,sm,f)=>`<div class="li" onclick="${f}"><span class="ico c${c}">${ic(i,20)}</span><div class="t"><span>${t}</span>${sm?`<small>${sm}</small>`:''}</div>${ic('chev',18)}</div>`;
 v.innerHTML=hd('Настройки')+`<div class="gt">Аккаунт</div><div class="grp">${it(1,'user','Профиль','@'+esc(ME.nick),'setProfile()')}${it(2,'lock','Пароль','','setPass()')}${it(3,'mail','Почта',ME.email?esc(ME.email)+(ME.email_ok?' ✓':' (не подтверждена)'):'не привязана','setMail()')}${it(6,'phone','Телефон',esc(ME.phone)||'нет','setPhone()')}</div>
 <div class="gt">Безопасность и приватность</div><div class="grp">${it(4,'key','Ключ доступа',ME.has_key?'создан':'нет','setKey()')}${it(2,'shield','Двухэтапная защита',ME.totp_on?'включена':'выключена','set2fa()')}${it(1,'eyeg','Конфиденциальность',ME.hide_seen?'«был(а) в сети» скрыто':'последний визит виден всем','setPriv()')}${it(6,'monitor','Устройства','','setDev()')}</div>
 <div class="gt">Nova</div><div class="grp">${it(5,'star','Premium',ME.prem?'до '+new Date(ME.prem_until*1000).toLocaleDateString():'50 ★ в месяц','setPrem()')}${it(1,'at','Мои юзернеймы','','setUn()')}${it(4,'msg','Мои боты','','setBots()')}${it(3,'palette','Фон чата','','setBgSheet()')}${it(3,'moon','Тёмная / светлая тема','','theme()')}</div>
 <div class="gt">Прочее</div><div class="grp">${it(6,'out','Выйти','','logout()')}${it(7,'trash','Удалить аккаунт','','delAcc()')}</div><div style="height:16px"></div>`}
function setProfile(){form('Профиль','День рождения: ДД.ММ, например 07.03',[['nick','Ник','text',ME.nick],['name','Имя','text',ME.name],['bio','О себе','text',ME.bio],['bday','День рождения (ДД.ММ)','text',ME.bday||'']],'Сохранить',v=>call('profile',v))}
function setPass(){form('Пароль','',[['old','Текущий пароль','password'],['new','Новый пароль (мин. 6)','password']],'Сменить',v=>call('password',v))}
function setMail(){form('Почта','Код придёт на почту (и копия в чат Nova Support).',[['email','Почта','email',ME.email]],'Отправить код',async v=>{const d=await api('email',v);if(d.error)return d.error;if(d.sent)setTimeout(()=>form('Код из письма','',[['code','Код']],'Подтвердить',x=>call('email/confirm',x)),200)})}
function setPhone(){form('Телефон','Системные номера +8880001488, +999, +777 — без кода (если свободны). Обычному номеру код придёт в чат Nova Support.',[['phone','Новый номер','tel',ME.phone],['code','Код (если запросит)']],'Сохранить',v=>call('phone/change',v))}
async function setPriv(){const b=await api('blocks');const s=sheet(`<div class="pad"><h2 style="font-size:20px;margin:6px 0 8px">Конфиденциальность</h2><div class="grp" style="margin:0"><div class="li" id="hs"><div class="t"><span>Скрыть «был(а) в сети»</span><small>Другие увидят «был(а) недавно»</small></div><div class="sw ${ME.hide_seen?'on':''}"></div></div></div><div class="gt" style="margin:18px 0 8px">Заблокированные (${b.items.length})</div><div class="grp" style="margin:0">${b.items.map(u=>`<div class="row" data-u="${u.id}">${ava(u,40)}<div class="t"><b>${esc(u.name)}</b><small>@${esc(u.nick)}</small></div><button class="lnk">Разблок.</button></div>`).join('')||'<div class="empty">Никого нет</div>'}</div></div>`);
 s.querySelector('#hs').onclick=async()=>{await api('privacy',{hide_seen:!ME.hide_seen});await refreshMe();s.remove();setPriv();vSet()};
 s.querySelectorAll('[data-u]').forEach(e=>e.onclick=async()=>{await api('block',{id:+e.dataset.u,off:true});s.remove();setPriv()})}
function setKey(){const s=sheet(`<div class="pad"><h2 style="font-size:20px;margin:6px 0 8px">Ключ доступа</h2><p class="note">Вход без пароля: ник + ключ. Ключ показывается один раз, сохрани его!</p><button class="btn" data-a="n">${ME.has_key?'Создать новый ключ':'Создать ключ'}</button>${ME.has_key?'<button class="btn bad" style="margin-top:10px" data-a="d">Удалить ключ</button>':''}<div id="kx"></div></div>`);
 s.querySelector('[data-a=n]').onclick=async()=>{const d=await api('key',{});s.querySelector('#kx').innerHTML=`<code>${d.key}</code>`;refreshMe()};
 const dl=s.querySelector('[data-a=d]');if(dl)dl.onclick=async()=>{await api('key/delete',{});s.remove();draw()}}
async function set2fa(){if(ME.totp_on)return form('Выключить 2FA','',[['code','Код из приложения']],'Выключить',v=>call('2fa/disable',v));
 const d=await api('2fa/setup',{});if(d.error)return toast(d.error);
 form('Двухэтапная защита','Добавь в Google Authenticator вручную (по ключу, тип «по времени»):<code>'+d.secret+'</code>',[['code','Код из приложения']],'Включить',v=>call('2fa/enable',v))}
async function setDev(){const d=await api('devices');const s=sheet(`<div class="pad"><h2 style="font-size:20px;margin:6px 0 10px">Устройства</h2><div class="grp" style="margin:0">${d.items.map(x=>`<div class="li"><span class="ico c6">${ic('monitor',20)}</span><div class="t"><span>${esc(x.device)}${x.cur?' (это устройство)':''}</span><small>${esc(x.place||x.ip)} · ${x.online?'в сети':when(x.seen)}</small></div>${x.cur?'':`<button class="lnk" data-k="${x.id}">Выйти</button>`}</div>`).join('')}</div><button class="btn bad" style="margin-top:12px" data-all="1">Завершить все остальные</button></div>`);
 s.querySelectorAll('[data-k]').forEach(b=>b.onclick=async()=>{await api('devices/kill',{id:+b.dataset.k});s.remove();setDev()});
 s.querySelector('[data-all]').onclick=async()=>{await api('devices/kill',{all:1});s.remove();setDev()}}
function setPrem(){const s=sheet(`<div class="pad" style="text-align:center"><div style="font-size:60px">⭐</div><h2 style="font-size:20px;margin:8px 0">Premium</h2><p class="note">Звезда рядом с твоим именем.</p><button class="btn" data-p="month">Месяц — 50 ★</button><button class="btn gl" style="margin-top:10px" data-p="year">Год — 100 ★</button></div>`);
 s.querySelectorAll('[data-p]').forEach(b=>b.onclick=async()=>{const d=await api('premium',{plan:b.dataset.p});s.remove();toast(d.error||'Premium активирован ⭐');draw()})}
async function setUn(){const d=await api('unames');const s=sheet(`<div class="pad"><h2 style="font-size:20px;margin:6px 0 8px">Мои юзернеймы</h2><p class="note">До 5 дополнительных @. NFT-юзернейм делает @Nova_NFT_bot (50 ★).</p><div class="grp" style="margin:0 0 12px">${d.items.map(x=>`<div class="li"><div class="t"><span>@${esc(x.name)} ${x.nft?'💎':''}</span><small>${x.show?'показывается в профиле':''}</small></div>${x.nft?`<button class="lnk" data-w="${esc(x.name)}" data-s="${x.show?1:0}">${x.show?'Скрыть':'Показать'}</button>`:`<button class="lnk" data-x="${esc(x.name)}">Удалить</button>`}</div>`).join('')||'<div class="empty">Пусто</div>'}</div><input id="un" placeholder="Новый юзернейм" autocapitalize="off" style="margin-bottom:10px"><div class="err" id="fe"></div><button class="btn" id="ua">Добавить</button></div>`);
 const re=()=>{closeAll();setUn();refreshMe()};
 s.querySelectorAll('[data-w]').forEach(b=>b.onclick=async()=>{await api('unames/wear',{name:b.dataset.s=='1'?'':b.dataset.w});re()});
 s.querySelectorAll('[data-x]').forEach(b=>b.onclick=async()=>{await api('unames/del',{name:b.dataset.x});re()});
 s.querySelector('#ua').onclick=async()=>{const r=await api('unames/add',{name:s.querySelector('#un').value});if(r.error)s.querySelector('#fe').textContent=r.error;else re()}}
async function setBots(){const d=await api('bots');const s=sheet(`<div class="pad"><h2 style="font-size:20px;margin:6px 0 8px">Мои боты</h2><p class="note">Бот отвечает на команды, которые ты задашь. На /start отвечает своим описанием.</p>${d.items.map(b=>`<div class="grp" style="margin:0 0 10px"><div class="li"><div class="t"><span>${esc(b.name)} @${esc(b.nick)}</span><small>${b.cmds.map(c=>esc(c.trig)).join(', ')||'команд нет'}</small></div><button class="lnk" data-c="${b.id}">+ команда</button></div></div>`).join('')}<button class="btn" id="nb">Создать бота</button></div>`);
 s.querySelectorAll('[data-c]').forEach(b=>b.onclick=()=>form('Новая команда','',[['trig','Команда, например /hi'],['reply','Ответ бота']],'Добавить',v=>call('bots/cmd',{bot:+b.dataset.c,trig:v.trig,reply:v.reply})));
 s.querySelector('#nb').onclick=()=>form('Новый бот','Юзернейм должен заканчиваться на bot.',[['nick','Юзернейм (my_bot)'],['name','Имя'],['desc','Описание']],'Создать',v=>call('bots/new',v))}
function theme(){const l=document.body.classList.toggle('light');try{localStorage.nova_theme=l?'light':'dark'}catch(e){}}
async function logout(){await api('logout',{});ME=null;welcome()}
/* 🗑 удаление аккаунта: отложенное (7 дней) или сразу */
function delAcc(){let inst=false;
 const s=sheet(`<div class="pad" style="text-align:center"><div style="font-size:60px">🗑</div><h2 style="font-size:20px;margin:8px 0">Удалить аккаунт?</h2>
 <div class="grp" style="margin:6px 0 12px;text-align:left"><div class="li"><span style="font-size:22px">⏳</span><div class="t"><span>Отложенное удаление</span><small style="white-space:normal">Через 7 дней. До этого ты выглядишь как «Удалённый аккаунт», а вход возвращает всё как было.</small></div></div><div class="li"><span style="font-size:22px">💥</span><div class="t"><span>Сразу навсегда</span><small style="white-space:normal">Сообщения, NFT, ★ и юзернеймы исчезнут без возврата.</small></div></div><div class="li"><span style="font-size:22px">👑</span><div class="t"><span>Группы</span><small style="white-space:normal">Владение перейдёт другому участнику.</small></div></div></div>
 ${ME.google?'':'<input id="dp" type="password" placeholder="Пароль" style="margin-bottom:10px">'}<input id="dw" placeholder="Напиши слово УДАЛИТЬ" autocapitalize="characters" style="margin-bottom:10px">${ME.totp_on?'<input id="dc" type="tel" placeholder="Код 2FA" style="margin-bottom:10px">':''}
 <div class="li" id="di" style="border-radius:16px;background:var(--card);margin-bottom:10px"><div class="t"><span style="text-align:left">Удалить сразу и навсегда</span></div><div class="sw"></div></div><div class="err" id="fe"></div><button class="btn bad" id="db">Удалить через 7 дней</button></div>`);
 s.querySelector('#di').onclick=()=>{inst=!inst;s.querySelector('#di .sw').classList.toggle('on',inst);s.querySelector('#db').textContent=inst?'Удалить навсегда сейчас':'Удалить через 7 дней'};
 s.querySelector('#db').onclick=async()=>{const d=await api('account/delete',{password:(s.querySelector('#dp')||{}).value||'',word:s.querySelector('#dw').value,code:(s.querySelector('#dc')||{}).value||'',now:inst});if(d.error)return s.querySelector('#fe').textContent=d.error;s.remove();ME=null;welcome();toast(d.instant?'Аккаунт удалён навсегда':'Аккаунт удалится через '+d.days+' дн. Войди снова, чтобы вернуть')}}

/* ───── МОЙ ПРОФИЛЬ ───── */
function vMe(){const u=ME,v=$('#v'),nx=u.next,pc=nx?Math.round((u.score-u.prev)/(nx-u.prev)*100):100;
 v.innerHTML=`<div class="cover ${u.bgn?'nf':''}" style="${u.bgn?cvs(u.bgn):''}">${sides(u.bgn)}<button class="ib gl" onclick="setProfile()">${ic('edit',20)}</button><div class="pav" onclick="chAv()">${ava(u,108)}<i>${ic('camera',18)}</i></div><h1>${vf(u,20)}${esc(u.name)}${bd(u)}</h1><p>@${esc(u.nick)}</p>${u.nu?`<span class="nuu">💎 @${esc(u.nu)}</span>`:''}${u.bio?`<p>${esc(u.bio)}</p>`:''}${u.bday?`<p style="font-size:13px">${bdayTxt(u.bday)}</p>`:''}<p style="font-size:13px">${esc(u.phone)}</p></div>
 <div class="stats"><div><b>★ ${u.stars}</b><span>Звёзды</span></div><div><b>${u.gifts}</b><span>Подарки</span></div><div onclick="rankInfo(${u.id},${u.lvl})"><b>${u.lvl}</b><span>Ранг</span></div></div>
 <div class="grp" style="padding:14px 16px"><div style="display:flex;align-items:center;gap:12px">${rk(u.lvl,40,u.id)}<div><b>${RN[u.lvl-1]}</b><div style="color:var(--mut);font-size:13px">Ранг ${u.lvl} из ${RN.length}</div></div></div><div class="pg"><i style="width:${pc}%"></i></div><small style="color:var(--mut)">${u.score} очков${nx?' · до следующего ранга '+(nx-u.score):' · максимум'}</small></div>
 <div class="grp">${li('📋 Скопировать @'+esc(u.nick),'cp')}${li('🎂 '+(u.bday?'День рождения: '+esc(u.bday):'Указать день рождения'),'bd')}${li('🎰 Крутить NFT-рулетку','nf')}</div><div style="height:16px"></div>`;
 v.querySelectorAll('[data-a]').forEach(e=>e.onclick=()=>{const a=e.dataset.a;if(a=='cp'){try{navigator.clipboard.writeText('@'+u.nick)}catch(_){}toast('Скопировано')}else if(a=='bd')setProfile();else if(a=='nf')go('gifts')})}
function chAv(){pick(async d=>{await api('avatar',{data:d});draw()})}

boot();
</script></body></html>"""

init_db()
threading.Thread(target=janitor, daemon=True).start()


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        a = s.getsockname()[0]
        s.close()
        return a
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    print("=" * 56)
    print(" Nova запущена!")
    print(" У тебя:               http://127.0.0.1:%d" % PORT)
    print(" Для друзей (Wi-Fi):   http://%s:%d" % (lan_ip(), PORT))
    if NGROK_TOKEN:
        try:
            from pyngrok import ngrok, conf
            conf.get_default().auth_token = NGROK_TOKEN
            print(" Публичная ссылка:     %s" % ngrok.connect(PORT).public_url)
        except Exception as e:
            print(" ngrok не запустился (%s). Установи: pip install pyngrok" % e.__class__.__name__)
    else:
        print(" Хочешь ссылку для всего интернета? Впиши NGROK_TOKEN вверху файла.")
    print("=" * 56)
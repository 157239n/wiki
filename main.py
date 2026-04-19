from k1lib.imports import *
import magic, trafilatura
from urllib.parse import urlparse, parse_qs
from schemaParser import *

settings.timezone = "Asia/Hanoi"

db = sql("dbs/main.db", mode="lite", manage=True)["default"]
db.query("""CREATE TABLE IF NOT EXISTS docs (
    id          INTEGER primary key autoincrement,
    url         TEXT,    -- full url of the document
    title       TEXT,    -- title of the site, taken from zircon
    content     TEXT,    -- main content of the page
    contentErr  TEXT,    -- if download not successful, contains the error and traceback. If successful, an empty string, if not executed, null
    createdTime INTEGER, -- unix time
    userId      INTEGER, -- user who owns this document
    chatId      INTEGER  -- chatId for this particular video summary. Can be a string for error message
);""")
db.query("""CREATE TABLE IF NOT EXISTS users ( -- this is just to keep track of what user has been initialized
    id          INTEGER primary key, -- no autoincrement because ground truth is on ai server's db
    scheduleId  INTEGER              -- scheduleId just for this wiki app
);""")

app = web.Flask(__name__)

@app.route("/test")
def test(): return "ok"

def sendAiServer(js): return requests.post("https://ai.aigu.vn/ingest?token=" + k1.aes_encrypt_json({"app": "yt", "timeout": int(time.time()) + 20}), json=js)
def tokenGuard(args):
    token = args.get('token', default=None)
    if not token: web.unauthorized("Token not found")
    obj = k1.aes_decrypt_json(token)
    if time.time() > obj["timeout"]: web.unauthorized("Token timed out")
    if "userId" in obj:
        userId = obj["userId"]; user = db["users"].lookup(id=userId)
        if user is None:
            res = sendAiServer({"cmd": "newSchedule", "userId": userId, "title": "Articles summaries (wiki app)"})
            if not res.ok: web.unauthorized(f"Tried to initialize user {userId} on ai.aigu.vn but can't for some reason: {res.text}")
            db["users"].insert(id=userId, scheduleId=int(res.text))
    obj["token"] = token; return obj

def docGuard(args, docId):
    obj = tokenGuard(args)
    if db["docs"].lookup(id=docId, userId=obj["userId"]) is None: web.unauthorized("User not authorized to view/modify this doc")
    return obj

@app.route("/", daisyEnv=True, guard=tokenGuard)
def index(guardRes):
    pre = init._jsDAuto()
    ui1 = db.query(f"select id, contentErr, length(content), chatId, createdTime, title from docs where userId = ? order by id desc", guardRes['userId']) | ~apply(lambda i,ce,lc,cId,ct,ti: [i,
            'none' if ce is None else ('error' if ce else 'yes'),lc,
            'none' if cId is None else ('error' if isinstance(cId, str) else cId),ct | toIso() | op().replace(*"T "),ti])\
        | deref() | (toJsFunc("term") | grep("${term}") | viz.Table(["id", "hasContent", "len(content)", "chatId", "createdTime", "title"], onclickFName=f"{pre}_select", selectable=True, height=400)) | op().interface() | toHtml()
    return f"""<style>#main {{ flex-direction: column-reverse; }} @media (min-width: 600px) {{ #main {{ flex-direction: row; }} }}</style><title>Local youtube service</title>
<div id="main" style="display: flex; flex-direction: column">
    <div style="display: flex; flex-direction: row; align-items: center; margin-bottom: 24px">
        <h2>Documents</h2>
        <input id="{pre}_url" class="input input-bordered" placeholder="(website url)" style="margin-left: 24px; margin-right: 8px" />
        <button id="{pre}_newBtn" class="btn">{k1.Icon.add()}</button>
    </div>
    <div style="overflow-x: auto; width: 100%">{ui1}</div>
    <div id="{pre}_res"></div></div>
<script>
    function {pre}_select(row, i, e) {{ dynamicLoad("#{pre}_res", `/mfragment/doc/${{row[0]}}?token={guardRes['token']}`); }}
    {pre}_newBtn.onclick = async () => {{ await wrapToastReq(fetchPost("/api/doc/new?token={guardRes['token']}", {{ url: {pre}_url.value.trim() }})); {pre}_url.value = ""; {pre}_url.focus(); }}
</script>"""

@app.route("/api/doc/new", methods=["POST"], guard=tokenGuard)
def api_doc_new(js, guardRes):
    if db["docs"].lookup(url=js["url"], userId=guardRes["userId"]): web.toast_error("Document added before!")
    db["docs"].insert(url=js["url"], createdTime=int(time.time()), userId=guardRes["userId"]); return "ok"

@app.route("/api/doc/<int:docId>/transcript", guard=docGuard)
def api_doc_transcript(docId):
    doc = db["docs"][docId]
    if doc is None: web.notFound()
    if doc.contentErr != "": web.notFound()
    return doc.content

@app.route("/mfragment/doc/<int:docId>", guard=docGuard)
def mfragment_doc(docId, guardRes):
    pre = init._jsDAuto(); doc = db["docs"][docId]; chatTag = ""; user = db["users"][doc.userId]; transTag = ""
    if doc.contentErr == "": transTag = f"""<textarea class="textarea textarea-bordered" style="width: 100%; height: 360px">{doc.content}</textarea>"""
    if isinstance(doc.chatId, int): chatTag = f" - <a href='https://ai.aigu.vn/schedules/{user.scheduleId}/{doc.chatId}' target='_blank' style='color: blue'>Summary</a>"
    return f"""<style>#{pre}_main {{ flex-direction: row; }} @media (max-width: 800px) {{ #{pre}_main {{ flex-direction: column }} }}</style>
<h2><a href="{doc.url}" target="_blank">{doc.title}</a>{chatTag}</h2>
<div id="{pre}_main" style="display: flex; gap: 12px">
    <div style="flex: 1">{transTag}</div>
    <div id="docHolder" style="flex: 1; display: grid; grid-template-columns: min-content auto; height: min-content; row-gap: 8px; column-gap: 8px; align-items: center">
        <button class="btn" onclick="wrapToastReq(fetch('/api/doc/{doc.id}/clear/contentErr?token={guardRes['token']}'))">Clear contentErr</button><div id="{pre}_2"></div>
        <button class="btn" onclick="wrapToastReq(fetch('/api/doc/{doc.id}/clear/chatId?token={guardRes['token']}'))"    >Clear chatId    </button><div id="{pre}_3"></div>
    </div></div>
<script>{pre}_2.innerHTML = {json.dumps(doc.contentErr)}; {pre}_3.innerHTML = {json.dumps(doc.chatId)};</script>"""

@app.route("/api/doc/<int:docId>/clear/<resource>", guard=docGuard)
def api_doc_clear(docId, resource, guardRes):
    doc = db["docs"][docId]
    if resource == "contentErr": doc.contentErr = None
    if resource == "chatId":
        if isinstance(doc.chatId, int):
            res = sendAiServer({"cmd": "deleteChat", "chatId": doc.chatId}) # deletes old chat from ai server, to prevent clogging things up
            if not res.ok or res.text.strip() != "ok": web.toast_error("Can't delete chat on ai.aigu.vn")
        doc.chatId = None
    return "ok"

@k1.cron(delay=10)
def docLoop(): # auto detects videos that need to be taken care of
    for doc in db["docs"].select("where contentErr is null limit 1"):
        print(f"doc: {doc.id}")
        with zircon.newBrowser() as b:
            try:
                b.pickExtFromGroup("site"); b.goto(doc.url); doc.title = b.document.title;
                doc.content = trafilatura.extract(b.querySelector("body").innerHTML); doc.contentErr = ""
            except Exception as e: doc.contentErr = f"error: {type(e)}\n{e}\n{traceback.format_exc()}"

@k1.cron(delay=10)
def summarizeLoop():
    for doc in db["docs"].select("where contentErr = '' and chatId is null"):
        user = db["users"][doc.userId]; print(f"summarize: {doc.id}")
        res = sendAiServer({"cmd": "scheduleNewChat", "scheduleId": user.scheduleId, "prompt": f"Please summarize the following document with length {len(doc.content)} bytes and title '{doc.title}' in detail, making sure result is nicely formatted:\n\n[begin document]\n```\n{doc.content}\n```\n[end document]"})
        try: doc.chatId = int(res.text.strip())
        except Exception as e: doc.chatId = f"error: {res.text.strip()}"

@toolCatchErr
def ytTranscript(vidId:str, env) -> str:
    """Get transcript of specific youtube video"""
    yield {"type": "status", "content": "Fetching transcript"}
    return api_vid_transcript(vidId)

toolsD = {"ytTranscript": ytTranscript}

@app.route("/ingest", methods=["POST"], guard=tokenGuard)
def ingest(js):
    if js["cmd"] == "toolCall":
        func = js["func"]; env = js["env"]; args = js["args"]
        if func in toolsD:
            it = ytTranscript(**{**args, "env": env})
            try:
                while True: x = next(it); yield (json.dumps({"type": "yield", "value": x}) | toBase64()) + "\n"
            except StopIteration as e: yield (json.dumps({"type": "return", "value": e.value}) | toBase64()) + "\n"
            return ""
    web.notFound("Don't understand this ingest message")

@app.route("/serverDef")
def serverDef(): # server definition so that it can be used by main ai server
    tools = [] | apply(function_to_ollama_tool) | apply(lambda x: {"server": "yt", "schema": x}) | aS(list)
    res = {"url": "https://wiki.aigu.vn", "name": "wiki", "descr": "Manages documents/websites", "tools": tools}; return json.dumps(res)

sql.lite_flask(app); k1.logErr.flask(app); k1.cron.flask(app)

app.run(host="0.0.0.0", port=5009) # same as normal flask code








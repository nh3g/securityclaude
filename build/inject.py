import base64, html, re, pathlib
SC = pathlib.Path("/tmp/claude-0/-home-user-securityclaude/286a1aba-26e1-5ba7-85b9-680fb8f38bc1/scratchpad")
SHOTS = SC/"entrega"/"shots"
html_in = (SC/"pdf"/"report.html").read_text(encoding="utf-8")

def datauri(key):
    p = SHOTS/(key+".png")
    b = p.read_bytes()
    return "data:image/png;base64," + base64.b64encode(b).decode()

def repl_img(m):
    return datauri(m.group(1))

out = re.sub(r"\{\{IMG:([^}]+)\}\}", repl_img, html_in)

# evidence transcript, HTML-escaped
evid = (SC/"evidencias.txt").read_text(encoding="utf-8")
out = out.replace("{{EVID}}", html.escape(evid))

(SC/"pdf"/"report.final.html").write_text(out, encoding="utf-8")
# sanity: no leftover placeholders
left = re.findall(r"\{\{[^}]+\}\}", out)
print("placeholders restantes:", left)
print("tamanho final (KB):", round(len(out.encode())/1024,1))

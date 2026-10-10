-- A stand-in for Rainmeter around the skin's script, for tests/test_skin_lua.py under lua5.1 (the Lua Rainmeter
-- embeds). Usage: lua5.1 skin_harness.lua <script.lua> <command> [args...]; prints one line per bang or value.
local script, command = arg[1], arg[2]
local vars = { ["@"] = "C:\\Skins\\AiSessionUsage\\@Resources\\" }
for i = 3, #arg do
    local k, v = arg[i]:match("^var:([^=]+)=(.*)$")
    if k then vars[k] = v end
end
local measures = {}
SKIN = {
    GetVariable = function(_, name) return vars[name] end,
    GetMeasure = function(_, name)
        return { GetStringValue = function() return measures[name] or "" end }
    end,
    -- A String meter's height after Rainmeter wrapped its text: 14 (one line) unless a test sets var:h:<meter>.
    GetMeter = function(_, name)
        local h = tonumber(vars["h:" .. name] or "") or 14
        return { GetH = function() return h end }
    end,
    Bang = function(_, ...)
        local parts = {}
        for i = 1, select("#", ...) do parts[#parts + 1] = tostring((select(i, ...))) end
        print("BANG\t" .. table.concat(parts, "\t"))
    end,
}
dofile(script)
if command == "json" then
    local v = TestJson(arg[3])
    local function dump(x)
        if type(x) == "table" then
            if tostring(x) == "null" then return "null" end
            local keys = {}
            for k in pairs(x) do keys[#keys + 1] = k end
            table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
            local out = {}
            for _, k in ipairs(keys) do out[#out + 1] = tostring(k) .. "=" .. dump(x[k]) end
            return "{" .. table.concat(out, ",") .. "}"
        end
        return tostring(x)
    end
    print(dump(v))
elseif command == "reset" then
    print(TestResetText(arg[3], tonumber(arg[4])))
elseif command == "layout" then
    -- args: var:... then answers as "answer:<provider>:<at>:<json>"; the layout is printed, one item per line
    local now = tonumber(vars.now or "0")
    for i = 3, #arg do
        local p, at, text = arg[i]:match("^answer:(%w+):(%d+):(.*)$")
        if p then TestAnswer(p, text, tonumber(at)) end
    end
    for _, item in ipairs(Layout(now)) do
        local parts = {}
        for j = 1, #item do parts[#parts + 1] = tostring(item[j]) end
        print(table.concat(parts, "\t"))
    end
elseif command == "init" then
    Initialize()
elseif command == "answer" then
    measures[arg[3]] = arg[4]
    Answer(arg[3] == "mClaude" and "claude" or "codex")
end

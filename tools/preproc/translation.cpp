#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include "preproc.h"
#include "translation.h"

Translation* g_translation = nullptr;

namespace {

// 读取整个文件到字符串；文件不存在时返回 false（不报错，便于默认关闭）。
bool ReadWholeFile(const std::string& path, std::string& out)
{
    FILE* fp = std::fopen(path.c_str(), "rb");

    if (fp == nullptr)
        return false;

    char chunk[4096];
    std::size_t count;

    while ((count = std::fread(chunk, 1, sizeof(chunk), fp)) != 0)
        out.append(chunk, count);

    std::fclose(fp);
    return true;
}

// 从 pos 起读取一个带引号的字面量，返回其内容（保留转义原样）。
// pos 必须指向开引号；成功后 pos 指向闭引号之后。
std::string ReadQuoted(const std::string& text, std::size_t& pos, const std::string& path, long lineNum)
{
    if (pos >= text.size() || text[pos] != '"')
        FATAL_ERROR("%s:%ld: expected '\"'\n", path.c_str(), lineNum);

    pos++; // 跳过开引号

    std::string result;

    while (pos < text.size() && text[pos] != '"')
    {
        if (text[pos] == '\\')
        {
            if (pos + 1 >= text.size())
                FATAL_ERROR("%s:%ld: unexpected EOF in escape sequence\n", path.c_str(), lineNum);

            result += text[pos];
            result += text[pos + 1];
            pos += 2;
            continue;
        }

        result += text[pos];
        pos++;
    }

    if (pos >= text.size())
        FATAL_ERROR("%s:%ld: unterminated string literal\n", path.c_str(), lineNum);

    pos++; // 跳过闭引号
    return result;
}

void SkipBlanks(const std::string& text, std::size_t& pos)
{
    while (pos < text.size() && (text[pos] == ' ' || text[pos] == '\t'))
        pos++;
}

} // namespace

Translation* Translation::Load(const std::string& charmapPath)
{
    std::string path;
    const char* env = std::getenv("OMP_TRANSLATION");

    if (env != nullptr)
    {
        // 显式指定；空串表示本次构建不启用翻译
        if (env[0] == '\0')
            return nullptr;

        path = env;
    }
    else
    {
        // 默认与 charmap.txt 同目录：translations/zh_CN.txt
        std::size_t slash = charmapPath.find_last_of("/\\");
        std::string dir = (slash == std::string::npos) ? std::string() : charmapPath.substr(0, slash + 1);
        path = dir + "translations/zh_CN.txt";
    }

    Translation* translation = new Translation();

    std::vector<std::string> includeStack;

    if (!translation->LoadFile(path, includeStack))
    {
        delete translation;
        return nullptr;
    }

    return translation;
}

bool Translation::LoadFile(const std::string& path, std::vector<std::string>& includeStack)
{
    for (std::size_t i = 0; i < includeStack.size(); i++)
    {
        if (includeStack[i] == path)
            FATAL_ERROR("%s: circular @include\n", path.c_str());
    }

    std::string text;

    if (!ReadWholeFile(path, text))
        return false;

    if (m_path.empty())
        m_path = path;

    includeStack.push_back(path);

    std::size_t pos = 0;
    long lineNum = 0;
    std::string scope;   // 当前 @file 限定的文件名；空表示全局

    while (pos <= text.size())
    {
        std::size_t lineEnd = text.find('\n', pos);

        if (lineEnd == std::string::npos)
            lineEnd = text.size();

        std::string line = text.substr(pos, lineEnd - pos);
        pos = lineEnd + 1;
        lineNum++;

        if (!line.empty() && line[line.length() - 1] == '\r')
            line.erase(line.length() - 1);

        std::size_t cursor = 0;
        SkipBlanks(line, cursor);

        if (cursor >= line.size() || line[cursor] == '#')
            continue;

        // @include "其它表文件"：路径相对于当前文件所在目录
        if (line.compare(cursor, 8, "@include") == 0)
        {
            cursor += 8;
            SkipBlanks(line, cursor);

            std::string included = ReadQuoted(line, cursor, path, lineNum);

            std::size_t slash = path.find_last_of("/\\");
            std::string dir = (slash == std::string::npos) ? std::string() : path.substr(0, slash + 1);

            if (!LoadFile(dir + included, includeStack))
                FATAL_ERROR("%s:%ld: cannot open included file \"%s\"\n",
                            path.c_str(), lineNum, included.c_str());

            continue;
        }

        // @file "路径"：其后条目只对该文件生效；@file 单独一行则恢复全局
        if (line.compare(cursor, 5, "@file") == 0)
        {
            cursor += 5;
            SkipBlanks(line, cursor);

            if (cursor >= line.size())
            {
                scope.clear();
            }
            else
            {
                scope = ReadQuoted(line, cursor, path, lineNum);

                SkipBlanks(line, cursor);
                if (cursor < line.size() && line[cursor] != '#' && line[cursor] != '@')
                    FATAL_ERROR("%s:%ld: unexpected trailing text after @file\n", path.c_str(), lineNum);
            }

            continue;
        }

        if (line[cursor] == '@')   // 其它 @ 开头的行是注释
            continue;

        std::string key = ReadQuoted(line, cursor, path, lineNum);

        SkipBlanks(line, cursor);

        if (cursor >= line.size() || line[cursor] != '=')
            FATAL_ERROR("%s:%ld: expected '=' after source text\n", path.c_str(), lineNum);

        cursor++;
        SkipBlanks(line, cursor);

        std::string value = ReadQuoted(line, cursor, path, lineNum);

        SkipBlanks(line, cursor);

        if (cursor < line.size() && line[cursor] != '#' && line[cursor] != '@')
            FATAL_ERROR("%s:%ld: unexpected trailing text\n", path.c_str(), lineNum);

        // 存成带引号的字面量，调用方可直接用 ParseString 解析
        std::string literal = "\"" + value + "\"";

        if (scope.empty())
        {
            if (m_entries.find(key) != m_entries.end())
                FATAL_ERROR("%s:%ld: duplicate entry for \"%s\"\n", path.c_str(), lineNum, key.c_str());
            m_entries[key] = literal;
        }
        else
        {
            std::string scoped = scope + '\n' + key;
            if (m_scopedEntries.find(scoped) != m_scopedEntries.end())
                FATAL_ERROR("%s:%ld: duplicate entry for \"%s\" under @file %s\n",
                            path.c_str(), lineNum, key.c_str(), scope.c_str());
            m_scopedEntries[scoped] = literal;
        }
    }

    includeStack.pop_back();
    return true;
}

const std::string* Translation::Lookup(const std::string& sourceText, const std::string& filename) const
{
    // 先看 @file 限定条目，其次全局条目
    if (!filename.empty())
    {
        std::string scoped = filename + '\n' + sourceText;
        std::unordered_map<std::string, std::string>::const_iterator sit = m_scopedEntries.find(scoped);

        if (sit != m_scopedEntries.end())
            return &sit->second;
    }

    std::unordered_map<std::string, std::string>::const_iterator it = m_entries.find(sourceText);

    if (it == m_entries.end())
        return nullptr;

    return &it->second;
}

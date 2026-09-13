// Copyright(c) 2016 YamaArashi
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.

#ifndef C_FILE_H
#define C_FILE_H

#include <cstdarg>
#include <cstdint>
#include <string>
#include <memory>
#include <utility>
#include <vector>
#include "preproc.h"

class CFile
{
public:
    CFile(const char * filenameCStr, bool isStdin);
    CFile(CFile&& other);
    CFile(const CFile&) = delete;
    ~CFile();
    void Preproc();

private:
    char* m_buffer;
    long m_pos;
    long m_size;
    long m_lineNum;
    std::string m_filename;
    bool m_isStdin;

    // C 文件先经 C 预处理器展开，#include 进来的头文件内容也会出现在这里，
    // 因此仅凭 m_filename 无法判断某个字符串究竟来自哪个文件（如 src/data/items.h
    // 被 src/item.c 包含）。预处理器会为每次切换来源输出 "# <行号> \"<文件>\"" 行标记，
    // 此处记录全部标记的位置，供按文件限定译文时还原真实来源。
    std::vector<std::pair<long, std::string>> m_lineMarkers;

    // 建立行标记索引；在构造函数读完文件后调用一次。
    void IndexLineMarkers();
    // 返回位置 pos 处字符串的真实来源文件；无标记时回退到 m_filename。
    const std::string& OriginFileAt(long pos) const;

    bool ConsumeHorizontalWhitespace();
    bool ConsumeNewline();
    void SkipWhitespace();
    void TryConvertString();
    std::unique_ptr<unsigned char[]> ReadWholeFile(const std::string& path, int& size);
    bool CheckIdentifier(const std::string& ident);
    void TryConvertIncbin();
    void ReportDiagnostic(const char* type, const char* format, std::va_list args);
    void RaiseError(const char* format, ...);
    void RaiseWarning(const char* format, ...);
};

#define CHUNK_SIZE 4096

#endif // C_FILE_H

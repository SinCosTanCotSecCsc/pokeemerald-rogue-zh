// 编译期文本本地化支持。
//
// 翻译以独立的数据文件存在，preproc 在把源码中的字符串交给 charmap 编码之前，
// 先按源文本查表；命中则改用译文解析。因此上游源码（src/、data/ 等）无需任何改动，
// 后续合并上游更新不会产生冲突，未登记的字符串自动回落到原文。
//
// 表文件格式：
//     "源文本" = "译文"                    # 全局条目
//     @include "其它表文件"                # 引入同目录下的另一个表
//     @file "src/data/text/move_names.h"   # 其后条目仅对该文件生效（优先于全局）
//     # 或 @ 开头（非指令）为注释
//
// 「按文件限定」是必要的：同一个英文串在不同语境下可能需要不同译法，
// 例如 "Rest" 在招式表中是「睡觉」，在界面文本中是「休息」。

#ifndef TRANSLATION_H
#define TRANSLATION_H

#include <string>
#include <unordered_map>
#include <vector>

class Translation
{
public:
    // 加载翻译表。charmapPath 为主 charmap 文件的路径，用于推导默认表位置。
    // 环境变量 OMP_TRANSLATION 可指定表路径；设为空串表示显式禁用翻译。
    // 表文件不存在时返回 nullptr（即不做任何翻译）。
    static Translation* Load(const std::string& charmapPath);

    // 按源字符串字面量的内容（不含首尾引号，保留 \n 等转义原样）查表。
    // filename 用于匹配 @file 限定的条目；未命中或为空时只看全局条目。
    // 未命中返回 nullptr。返回值为带首尾引号的译文，可直接交给 ParseString 解析。
    const std::string* Lookup(const std::string& sourceText, const std::string& filename) const;

    std::size_t Count() const { return m_entries.size() + m_scopedEntries.size(); }
    const std::string& Path() const { return m_path; }

private:
    // 加载单个表文件；includeStack 用于解析 @include 并防止循环引用。
    bool LoadFile(const std::string& path, std::vector<std::string>& includeStack);

    // 全局条目：键为源文本
    std::unordered_map<std::string, std::string> m_entries;
    // 文件限定条目：键为「文件名 + '\n' + 源文本」
    std::unordered_map<std::string, std::string> m_scopedEntries;

    std::string m_path;
};

// 全局翻译表，由 preproc.cpp 在启动时设置；为 nullptr 时所有字符串按原文处理。
extern Translation* g_translation;

#endif // TRANSLATION_H

#include "global.h"
#include "text.h"
#include "chinese_text.h"

//汉字在 charmap.txt 中使用双字节编码：高位 0x01-0x1E（单字节编码的 À 到 ì），低位 0x00-0xF6。
//高位 0x06（É）与 0x1B（é）是常用重音拉丁字母，不参与汉字编码。
//注意：日文平假名同样占用 0x01-0x50，与本编码的高位区间重叠，
//因此必须排除日文文本与盲文字体（盲文编码为 0x00-0x3F，同样重叠）。
bool8 IsChineseChar(u16 currChar, u16 nextChar, u8 fontId, bool32 isJapanese)
{
    //排除日文文本、盲文字体
    if (isJapanese == TRUE || fontId == FONT_BRAILLE)
        return FALSE;

    //检查汉字编码双字节高位是否满足要求
    if (currChar >= 0x01 && currChar <= 0x1E && currChar != 0x06 && currChar != 0x1B)
    {
        //检查汉字编码双字节低位是否满足要求
        if (nextChar <= 0xF6)
            return TRUE;
    }

    //不符合汉字编码条件
    return FALSE;
}

//仅在通过IsChineseChar检测后使用
void DecompressGlyph_Chinese(u16 chineseChar, u8 fontId)
{
    const u16 *glyphs;
    u16 glyphId, hi, lo;
    u8 width;

    //汉字编码转换为字模索引编号（跳过 0x06 与 0x1B 两个留空的高位块）
    hi = chineseChar >> 8;
    lo = chineseChar & 0xFF;
    if (hi > 0x1B)
        hi -= 0x01;
    if (hi > 0x06)
        hi -= 0x01;
    hi -= 0x01;
    glyphId = (hi << 8) | lo;

    //根据字体类别选择字体库
    if (fontId == FONT_SMALL || fontId == FONT_SMALL_NARROW)
        glyphs = gFontSmallChineseGlyphs + (0x20 * glyphId);
    else
        glyphs = gFontNormalChineseGlyphs + (0x20 * glyphId);

    width = GetChineseFontWidthFunc(fontId);
    gCurGlyph.width = width;
    gCurGlyph.height = width + 3;

    //将汉字字模存入内存
    DecompressGlyphTile(glyphs, gCurGlyph.gfxBufferTop);
    DecompressGlyphTile(glyphs + 0x8, gCurGlyph.gfxBufferTop + 8);
    DecompressGlyphTile(glyphs + 0x10, gCurGlyph.gfxBufferBottom);
    DecompressGlyphTile(glyphs + 0x18, gCurGlyph.gfxBufferBottom + 8);
}

//仅在通过IsChineseChar检测后使用
u8 GetChineseFontWidthFunc(u8 fontId)
{
    //小字字体使用小字字库，宽度 10；其余字体使用大字字库，宽度 12
    switch (fontId)
    {
    case FONT_SMALL:
    case FONT_SMALL_NARROW:
        return 10;
    default:
        return 12;
    }
}

//汉字小字字库
ALIGNED(4) const u16 gFontSmallChineseGlyphs[] = INCBIN_U16("graphics/fonts/chinese_small.fwlatfont");

//汉字大字字库
ALIGNED(4) const u16 gFontNormalChineseGlyphs[] = INCBIN_U16("graphics/fonts/chinese_normal.fwlatfont");

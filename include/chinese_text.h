#ifndef GUARD_CHINESE_TEXT_H
#define GUARD_CHINESE_TEXT_H

bool8 IsChineseChar(u16 currChar, u16 nextChar, u8 fontId, bool32 isJapanese);
void DecompressGlyph_Chinese(u16 chineseChar, u8 fontId);
u8 GetChineseFontWidthFunc(u8 fontId);

extern const u16 gFontSmallChineseGlyphs[]; //汉字小字体字模
extern const u16 gFontNormalChineseGlyphs[]; //汉字大字体字模

#endif //GUARD_CHINESE_TEXT_H

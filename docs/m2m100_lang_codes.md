# M2M100 语言与代码对照表（facebook/m2m100_418M）

以下列表来自 Hugging Face 模型仓库 `facebook/m2m100_418M` 的 “Languages covered” 段落，方便在使用 M2M100 时查找正确的语言代码。

原始来源（建议收藏）：  
https://huggingface.co/facebook/m2m100_418M

| 语言名称（英文/说明）                        | 代码 |
|-------------------------------------------|------|
| Afrikaans                                 | af   |
| Amharic                                   | am   |
| Arabic                                    | ar   |
| Asturian                                  | ast  |
| Azerbaijani                               | az   |
| Bashkir                                   | ba   |
| Belarusian                                | be   |
| Bulgarian                                 | bg   |
| Bengali                                   | bn   |
| Breton                                    | br   |
| Bosnian                                   | bs   |
| Catalan; Valencian                        | ca   |
| Cebuano                                   | ceb  |
| Czech                                     | cs   |
| Welsh                                     | cy   |
| Danish                                    | da   |
| German                                    | de   |
| Greek                                     | el   |
| English                                   | en   |
| Spanish                                   | es   |
| Estonian                                  | et   |
| Persian                                   | fa   |
| Fulah                                     | ff   |
| Finnish                                   | fi   |
| French                                    | fr   |
| Western Frisian                           | fy   |
| Irish                                     | ga   |
| Gaelic; Scottish Gaelic                   | gd   |
| Galician                                  | gl   |
| Gujarati                                  | gu   |
| Hausa                                     | ha   |
| Hebrew                                    | he   |
| Hindi                                     | hi   |
| Croatian                                  | hr   |
| Haitian; Haitian Creole                   | ht   |
| Hungarian                                 | hu   |
| Armenian                                  | hy   |
| Indonesian                                | id   |
| Igbo                                      | ig   |
| Iloko                                     | ilo  |
| Icelandic                                 | is   |
| Italian                                   | it   |
| Japanese                                  | ja   |
| Javanese                                  | jv   |
| Georgian                                  | ka   |
| Kazakh                                    | kk   |
| Central Khmer                             | km   |
| Kannada                                   | kn   |
| Korean                                    | ko   |
| Luxembourgish; Letzeburgesch              | lb   |
| Ganda                                     | lg   |
| Lingala                                   | ln   |
| Lao                                       | lo   |
| Lithuanian                                | lt   |
| Latvian                                   | lv   |
| Malagasy                                  | mg   |
| Macedonian                                | mk   |
| Malayalam                                 | ml   |
| Mongolian                                 | mn   |
| Marathi                                   | mr   |
| Malay                                     | ms   |
| Burmese                                   | my   |
| Nepali                                    | ne   |
| Dutch; Flemish                            | nl   |
| Norwegian                                 | no   |
| Northern Sotho                            | ns   |
| Occitan (post 1500)                       | oc   |
| Oriya                                     | or   |
| Panjabi; Punjabi                          | pa   |
| Polish                                    | pl   |
| Pushto; Pashto                            | ps   |
| Portuguese                                | pt   |
| Romanian; Moldavian; Moldovan             | ro   |
| Russian                                   | ru   |
| Sindhi                                    | sd   |
| Sinhala; Sinhalese                        | si   |
| Slovak                                    | sk   |
| Slovenian                                 | sl   |
| Somali                                    | so   |
| Albanian                                  | sq   |
| Serbian                                   | sr   |
| Swati                                     | ss   |
| Sundanese                                 | su   |
| Swedish                                   | sv   |
| Swahili                                   | sw   |
| Tamil                                     | ta   |
| Thai                                      | th   |
| Tagalog                                   | tl   |
| Tswana                                    | tn   |
| Turkish                                   | tr   |
| Ukrainian                                 | uk   |
| Urdu                                      | ur   |
| Uzbek                                     | uz   |
| Vietnamese                                | vi   |
| Wolof                                     | wo   |
| Xhosa                                     | xh   |
| Yiddish                                   | yi   |
| Yoruba                                    | yo   |
| Chinese                                   | zh   |
| Zulu                                      | zu   |

> 提示：在代码中使用 M2M100 时，一般需要传入上表中的语言代码（例如 `en`、`zh`、`fr`），并结合 `tokenizer.src_lang` 与 `tokenizer.get_lang_id(target_code)` 使用。当前项目中的 `M2M100Translator` 已做了部分别名映射（如 `EN` / `EU` / `zh-CN` 自动归一到 `en` / `zh`），更复杂的映射可以参考此表自行扩展。


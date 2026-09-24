"""
known_sites_data.py

Part of ARIYAN GEO AI -- F1 Known-Site Layer (added 2026-09-24).

DATA ONLY, no logic. Generated mechanically from the real published file
"ANE.kmz" (md5 3c46cf4f2595fe86a1ceaa2146a21c09), record
"ANE Site Placemarks for Google Earth", version 10, by Olof Pedersen
(Uppsala University), Zenodo, DOI 10.5281/zenodo.6384045,
licensed CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/).
Attribution is required: keep this header whenever the data is used.

Nothing was added, invented or edited except: coordinates rounded to
5 decimals (~1 m), whitespace in names collapsed, and '|' replaced by
'/' in names (it is the field separator below).

POINTS: one site per line, kind|name|lat|lon
  kind S = placemark in the "Sites" folder (named site)
  kind N = placemark in the "No names" folder; its name is only a
           region code from the source (e.g. SIRAQ, WIRAN), not a
           site name
EXTENTS: outlines of large ancient city extents from the source's
  "Extensions" folder, one per line, name|lat,lon;lat,lon;...

COVERAGE WARNING (measured 2026-09-24): dense for Iraq/Syria, thin for
Iran (roughly 250 points, mostly well-known sites). Absence of a nearby
point is NOT evidence that a place is unrecorded.
"""

SOURCE_DOI = "10.5281/zenodo.6384045"
SOURCE_LICENSE = "CC-BY-4.0"
SOURCE_CITATION = "Pedersen, O. ANE Site Placemarks for Google Earth, v10. Zenodo. doi:10.5281/zenodo.6384045"
SOURCE_KMZ_MD5 = "3c46cf4f2595fe86a1ceaa2146a21c09"

POINTS = """\
S|Adab (Bismaya)|31.95071|45.62386
S|Abydos|26.18509|31.91906
S|Adamdun? (Teppe Surkhehgan)|32.02168|48.79814
S|Admannu / Natmane (Tell 'Ali)|35.38198|43.68200
S|Aila ('Aqaba)|29.53070|34.99985
S|Adumatu? (Dumat el-Jandal)|29.81135|39.86723
S|Akhetaten (El-'Amarna)|27.65033|30.90068
S|Akkû / 'Akkô (Tell el-Fukhkhar)|32.92139|35.08776
S|Akzibu / Akzib (ez-Zib)|33.04858|35.10194
S|Alexandria|31.19676|29.90343
S|Alalakh (Tell Açana)|36.23761|36.38418
S|Amida (Diyarbakir)|37.91085|40.23676
S|Alexandria / Charax Spasinou (Naisan / Khayabir)|30.89469|47.57803
S|Alexandria on Oxus (Ai Khanum)|37.16488|69.41166
S|Amman / Philadelphia|31.95431|35.93515
S|Amrit|34.83512|35.91208
S|Anasarta (Khanasir)|35.77684|37.49760
S|Amqaruna / Eqron (Tel Miqne / Khirbat el-Muqanna')|31.77760|34.85093
S|Anat (Qal'at 'Ana)|34.46761|41.97943
S|Androna (El-Andarin)|35.53431|37.36227
S|Ankuwa (Alişar Hüyük)|39.60608|35.26133
S|Ankyronpolis / Teudjoi (El-Hiba)|28.78731|30.92107
S|Anšan (Tell Malyan)|30.01111|52.41067
S|Antiokia (Antakya)|36.21256|36.17008
S|Anzilija? (Zile)|40.30410|35.89057
S|Apamea|35.42070|36.40153
S|Apamea|37.06484|37.87177
S|Aphek / Pegae / Antipatris (Tel Ras el-'Ain)|32.10478|34.93078
S|Aphroditopolis / Tepihu (Atfih)|29.40770|31.25303
S|Apqu (Tell Abu Maria)|36.42959|42.59760
S|Arad|31.28101|35.12633
S|Araziqa? (Tell el-Hajj)?|36.19557|38.07598
S|Arbela (Irbid)|32.55913|35.84748
S|Arbatu? (Tell Khaumat Hajin)|34.71263|40.82606
S|Ardashir Khureh / Gur (Firuzabad)|28.85181|52.53243
S|Ardata (Tell Ardé)|34.40849|35.91467
S|Argištihinili (Davti-blur)|40.08133|44.03411
S|Arpadda (Tell Rifa'at)|36.47262|37.09464
S|Arrapha (Kirkuk)|35.46963|44.39572
S|Artemita? (Karastel D74)|33.80051|44.77776
S|Arwad|34.85621|35.85873
S|Ashdod / Asdudu (Tel Ashdod)|31.75604|34.65606
S|Asdudimmu (Ashdod Yam / Minat el-Qal'a)|31.77961|34.62150
S|Asdudimmu (Tel Mor)|31.82292|34.65631
S|Ašnakkum? (Chagar Bazar)|36.87559|40.89771
S|Ašqaluna / Isqaluna / Ashqelon|31.66426|34.54732
S|Aššur (Qal'at Sherqat)|35.45626|43.25979
S|Astartu / Ashtarot (Tell Ashtara)|32.80428|36.01554
S|Asyut / Lykopolis|27.17922|31.18406
S|'Ataroth (Khirbet 'Ataruz)|31.57431|35.66497
S|Athens|37.97142|23.72678
S|Athribis (Tell Atrib)|30.47059|31.18689
S|Avaris / Piramesse (Tell ed-Dab'a)|30.78880|31.82209
S|Awal (Tell es-Suleimeh)|34.16758|45.10316
S|Azamhul? (Tell Muhammed Diyab)|36.92458|41.56394
S|Azatiwadaya (Karatepe Aslantaş)|37.29594|36.25399
S|Azeqa (Tell Zakariya)|31.70110|34.93631
S|Azu (Tell Hadidi)|36.26368|38.15089
S|Babylon|32.54036|44.42633
S|Babylon (Qasr el-Shamee)|30.00590|31.23029
S|Bad-Tibira (Tell Medinah/Madain)|31.38245|46.00365
S|Bakchias (Kom Umm el-Atl)|29.54100|31.00846
S|Balaṭu? (Eski Mosul)|36.51081|42.73664
S|Bargâ? (Barqum)|36.03750|36.96640
S|Baṣiru (Tell Bazi)|36.42731|38.27608
S|Batruna / Botrus (Batrun)?|34.25516|35.65831
S|Beersheva (Tell es-Saba')|31.24500|34.84068
S|Behistun|34.38693|47.43300
S|Berenike|23.91032|35.47590
S|Betel (Beitin)?|31.92623|35.23913
S|Bet Shean / Bit-Sani / Scythopolis (Tell el-Hosn)|32.50419|35.50300
S|Bet-Shemesh (Tel Bet-Shemesh)|31.75064|34.97458
S|Bi'rutu / Bi'rû /Berytos (Beirut)|33.89896|35.50724
S|Bishapur|29.77730|51.57143
S|Bit-Adad-eriba? (Tell Baqaq 1-2)|36.68305|42.93540
S|Borsippa (Birs Nimrud)|32.39212|44.34201
S|Boṣra? (Buṣeirah)|30.74622|35.60380
S|Bubastis (Tell Basta)|30.57144|31.51411
S|Buhen?|21.91534|31.28393
S|Burmarina (Tell esh-Shiyukh Fawqani)|36.78755|38.03597
S|Burušhanda? (Açemhöyük)|38.41159|33.83548
S|Busiris (Abu Sir Bana)|30.90945|31.24454
S|Buṣruna / Bosra (Buṣra')|32.52001|36.48214
S|Buto (Tell el-Fara'in)|31.19597|30.74244
S|Byzantion / Konstantinopel (Istanbul)|41.01244|28.95641
S|Caesarea|32.49872|34.89118
S|Carthago / Qart Hadasht|36.85096|10.32634
S|Chalcis (El-'Is / Qinnasrin)|35.98932|37.00384
S|Circesium (Buseire)|35.15668|40.42791
S|Cunaxa? (Tell Kuneise)|33.23313|43.86867
S|Cyrene (Shahat)|32.81970|21.85384
S|Cyrrhus|36.74461|36.95892
S|Dabigu / Dabekov (Tell Dabiq)|36.53976|37.26849
S|Damaskus|33.51012|36.30921
S|Damdammusa? (Kaziktepe)|37.77647|40.27580
S|Dan (Tell Qadi)|33.24856|35.65252
S|Daphnae (Kom Dafana)|30.85626|32.17969
S|Daskara (Bint el-Emir D41)|33.93651|44.92968
S|Dedan?|26.66663|37.91062
S|Deir el-'Aqul (Tell ed-Deir D791)|32.87807|44.98653
S|Der (Tell Aqar)|33.12349|45.93197
S|Diban|31.50182|35.77646
S|Dilbat (Deilam)|32.29572|44.46622
S|Diniktum? (D851)|32.83361|45.34362
S|Diospolis Parva (Hiw)|26.02152|32.28277
S|Dor / Du'ru (Tel Dor / Khirbet el-Burj)|32.61630|34.91627
S|Dunnu-ša-Uzibi (Giricano)|37.81701|40.75006
S|Dura Europos (Qal'at es-Salihiye)|34.74792|40.73059
S|Dur-Aššur? (Bakr Awa)|35.22150|45.94018
S|Dur-Aššur-ketti-lešer (Tell Bderi)|36.38755|40.81369
S|Dur-Jakin (Tell Abu Salabikh)|30.76002|47.17052
S|Dur-Katlimmu / Magdala (Tell Sheikh Hamad)|35.64564|40.74325
S|Dur-Kurigalzu (Aqar Quf)|33.35466|44.20080
S|Dur-Šamši-Adad? (Qal'at Halwanji)|36.64407|37.90458
S|Dur-Samsuiluna (Khafaja B)|33.35096|44.54956
S|Dur-Šarrukin (Khorsabad)|36.50365|43.23367
S|Dur-Untaš (Chogha Zanbil)|32.00811|48.52227
S|Ebla (Tell Mardikh)|35.79888|36.79831
S|Edessa / Urfa|37.15211|38.78947
S|Edfu|24.97772|32.87323
S|Ekalte (Tell Munbaqa)|36.21745|38.12976
S|Elephantine|24.08536|32.88593
S|Emar / Barbalissus (Tell Meskene)|35.98641|38.11320
S|Emesa (Hims)|34.72350|36.71444
S|'En Gedi (Tel Goren)|31.46017|35.38899
S|Enu-Šasî? (Tell 'Ayn Sharif)|33.89112|36.02633
S|Ephesus / Apaša?|37.93966|27.34674
S|Erbil|36.19143|44.00901
S|Erebuni (Arin-berd)|40.14063|44.53810
S|Eridu (Tell Abu Shahrain)|30.81687|45.99672
S|Ešnunna (Tell Asmar D244)|33.48423|44.72803
S|Eufemeria (Tell Qasr el-Banat)|29.37367|30.54304
S|Forat? (Maghloub)|30.78305|47.70516
S|Gabbari-ibni (Sur Jur'eh)|34.30692|42.19386
S|Gadara (Umm Qeis)|32.65692|35.67797
S|Garšana (Tall Baridiyah)|31.44332|46.11919
S|Gasur / Nuzi (Yorgan Teppe)|35.36956|44.25488
S|Gath (Tell es-Safi)|31.70329|34.84952
S|Gazziura (Turhal)|40.38858|36.09231
S|Gerasa (Jerash)|32.28023|35.89303
S|Gezer / Gazru (Tell Jazar)|31.85958|34.92048
S|Giba'la (Tell Tuweini)|35.37166|35.93654
S|Gib'at Shaul (Tell el-Ful)|31.82221|35.23103
S|Gibeon (El-Jib)|31.84668|35.18520
S|Gindaros (Tell Jindiris)|36.38537|36.68863
S|Girsu (Tello)|31.55847|46.17758
S|Girumu (Tell Barghuthiat / Ishan Khilala K94)|32.70231|44.79478
S|Gordion (Yassihüyük)|39.65010|31.97857
S|Gubla (Byblos)|34.11880|35.64646
S|Gundeshapur|32.28225|48.51226
S|Guzana (Tell Halaf)|36.82619|40.03950
S|Hadatu (Arslan Tash)|36.84881|38.40810
S|Halab (Aleppo)|36.19922|37.16272
S|Haldiei Ziuquni (Kef Kalesi)|38.83050|42.72032
S|Hama|35.13590|36.74950
S|Hamadan / Ecbatana (Teppe-ye Hekmatana)|34.80523|48.51696
S|Hanusa (Khinis)|36.75612|43.41404
S|Haradu (Khirbet ed-Diniye)|34.46112|41.58634
S|Harbe (Tell Huera)|36.64699|39.49853
S|Harran|36.86626|39.03155
S|Hašabu? (Tell 'Ayn 'Ushba / Tell Hashba)?|33.94695|36.05370
S|Hatarikka (Tell Afis)|35.90500|36.79875
S|Hatra (el-Hadhar)|35.58703|42.71855
S|Hattuša (Boğazköy)|40.01520|34.61500
S|Hazazu? ('Azaz)|36.58601|37.04466
S|Hazi? (Tell Hizzin)|33.96493|36.10403
S|Hazor|33.01754|35.56824
S|Hazzat / Gaza (Tell Harube / Tell 'Azza)|31.54734|34.51384
S|Hecatompylos (Shahr-e Qumis)|35.95289|54.11851
S|Heliopolis (Baalbek)|34.00676|36.20437
S|Heliopolis / Iunu|30.12944|31.30676
S|Herakleopolis Magna (Inasya el-Medina)|29.08673|30.93844
S|Herakleopolis Parva (Tell Belim)|30.97813|32.17544
S|Hermonthis (Armant)|25.62035|32.54686
S|Hermopolis Magna / Khmun (El-Ashmunein)|27.78125|30.80337
S|Hermopolis Parva / Damanhur|31.03284|30.47150
S|Hermopolis (Tell en-Naqus)|30.95200|31.43301
S|Herodion (Jebel Fureidis)|31.66576|35.24179
S|Heshbon (Tell Hesban)|31.80056|35.80903
S|Hierakonpolis / Nekhen (Kom el-Ahmar)|25.09745|32.77962
S|Hildua (Khalda)?|33.78546|35.48016
S|Hinatuna / Hannaton (Tel Hannaton / Tell el-Badawiya)|32.78548|35.25645
S|Hindanu (Karable)|34.38272|41.06436
S|Hippos (Qala'at el-Husn)|32.77840|35.65999
S|Hupišna / Hubušnu / Kybistra (Karahüyük)|37.66236|34.22691
S|Hupšana (Deh-e Now)|32.06841|48.56805
S|Huri-ṣubu'i (Khraṣbo)?|35.61419|35.87285
S|Hursagkalama (Ingharra)|32.54012|44.60449
S|Huzirina (Sultantepe)|37.05030|38.90624
S|Idalion / Edi'il (Dali)|35.01609|33.42482
S|Idu (Satu Qala)|35.87415|44.69656
S|Ilansura? (Tell Farfara)|36.82263|41.33237
S|Ilištam'u? (Stamo)?|35.48425|35.91584
S|Imaw / Momemphis (Kom el-Hisn)|30.79512|30.60060
S|Imgur-Enlil (Balawat)|36.22945|43.40327
S|Irgilli? (Tell Irjil)|35.84846|37.22539
S|Irqata (Tell 'Arqa)|34.53049|36.04677
S|Irrita (Oylum Höyük)|36.69864|37.17903
S|Isin (Ishan Bahriyat)|31.88438|45.26937
S|Issos (Kinet Höyük)|36.85375|36.15682
S|Istakhr|29.98133|52.90922
S|Itu'u (Hit)|33.64392|42.82332
S|Jabrudu (Yabrud)|33.96665|36.65996
S|Jahariša (Tell Fray)|35.90354|38.38420
S|Jappû / Ioppe (Yafa)|32.05406|34.75264
S|Jericho (Tell es-Sultan)|31.87110|35.44398
S|Jericho (Tulul Abu el-'Alaiq North)|31.85321|35.43510
S|Jericho (Tulul Abu el-'Alaiq South)|31.85052|35.43621
S|Jerusalem|31.77461|35.23595
S|Jokneam (Tel Yoqne'am)|32.66467|35.10883
S|Kabnak (Haft Teppe)|32.08057|48.32808
S|Kadeš Barnea? (Tell el-Qudeirat)|30.64805|34.42261
S|Kafar Nahum (Capharnaum)|32.88093|35.57543
S|Kahat (Tell Barri)|36.73893|41.12701
S|Kalhu (Nimrud)|36.09863|43.32932
S|Kaneš/Neša (Kültepe)|38.85017|35.63529
S|Karanis (Kom Aushim)|29.51801|30.90327
S|Kar-Assurnasirpal (Jebel Masaikh)|34.97380|40.55546
S|Karkara? (Tell Jidr U004)|31.82422|45.70486
S|Karkemish|36.82892|38.01623
S|Kar-Mullissi (Keramlais)|36.30564|43.40966
S|Kar-Tukulti-Ninurta (Tulul el-'Aqir)|35.49355|43.27538
S|Kasappa (Tell Kashaf)|35.99827|43.36426
S|Kelenderis / Ura? (Aydıncık)|36.14408|33.32306
S|Kilizu (Qasr Shamamok EPAS 2)|36.10508|43.75206
S|Kirši (Meydancıkkale)?|36.27372|33.44177
S|Kiryat Ye'arim|31.80933|35.10370
S|Kiš (Tell Uhaimir)|32.55202|44.58563
S|Kissik / Duru? (Tell el-Lahm)|30.77403|46.36579
S|Kisurra (Abu Hatab)|31.83782|45.48128
S|Kition (Larnaca)|34.92021|33.63275
S|Knossos|35.29798|25.16300
S|Koptos (Qift)|25.99746|32.81569
S|Krak des Chevallier / Qala'at el-Husn|34.75701|36.29474
S|Krokodilopolis / Arsinoe (Kiman Faris / Medinet el-Fayyum)|29.32170|30.83463
S|Ktesiphon (Salman-pak)|33.09367|44.58129
S|Kullania (Tell Tayinat)|36.24858|36.37573
S|Kullimeri? (Gre Migro)|37.99100|41.15723
S|Kumidu (Kamid el-Loz)|33.62382|35.82143
S|Kummanni? / Comana Cappadociae (Şar)|38.33063|36.32538
S|Kummuhu / Samosata (Samsat)|37.50356|38.49886
S|Kurî / Kourion (Episkopi)|34.67277|32.86384
S|Kutallu (Tell Ṣifir)|31.29483|45.96716
S|Kutû / Gudua / Kutha (Tell Ibrahim)|32.76052|44.61209
S|Laba'u / Lebo (Tell Qasr Labwa)|34.19973|36.34379
S|Lagaš (El-Hiba)|31.41790|46.41028
S|Lakišu / Lakisu / Lachish (Tell ed-Duwer)|31.56522|34.84907
S|Larak? (Tell Wilaya)|32.31211|45.66116
S|Larsa (Tulul Sinkara)|31.28289|45.85330
S|Leontopolis (Tell el-Moqdam)|30.67955|31.35799
S|Liyan (Sabzabad Bushehr)?|28.90649|50.84723
S|Madaba|31.71470|35.79230
S|Magrisu (Tell Hasaka)?|36.49933|40.75108
S|Malgium (Tell Yassir)|32.56149|45.10002
S|Manṣuate? (Masyaf)|35.06586|36.34312
S|Marad (Tell es-Sadum)|32.09228|44.78425
S|Margu / Antiokia Margiana (Merv / Erk Kala / Gyaur Kala)|37.66922|62.19209
S|Mardaman / Mardama (Bassetki)|36.95844|42.72121
S|Mari (Tell Hariri)|34.55049|40.89003
S|Marib|15.42575|45.33242
S|Marqas / Gurgum / Germanikeia (Kahramanmaraş)|37.58709|36.92543
S|Maškan-šapir (Tell Abu Duwari H639)|32.40592|45.22082
S|Masada|31.31552|35.35363
S|Matiate (Midyat)?|37.41419|41.37739
S|Megiddo (Tell el-Mutasallim)|32.58505|35.18452
S|Melid (Arslantepe)|38.38189|38.36103
S|Memphis|29.85544|31.25644
S|Mendes (Tell er-Ruba)|30.95614|31.51744
S|Mendes / Thmuis (Tell el-Timai)|30.93864|31.51692
S|Meroe|16.93752|33.71271
S|Mê Turan (Tell Baradan)|34.19115|45.05112
S|Miletus / Milawanda?|37.53127|27.28031
S|Moza (Tel Moza)|31.79410|35.16477
S|Mugdan? (Umm el-Jir K97)|32.64980|44.85018
S|Muṣaṣir? (Muǧesir)|36.80353|44.59303
S|Mycene|37.73007|22.75775
S|Nabada (Tell Beidar)|36.73799|40.58712
S|Nagar (Tell Brak)|36.66733|41.05793
S|Nagsu? (U175)|31.69662|45.78303
S|Nahrawan (Tell Isheiri / Sifwah D309)|33.43170|44.58229
S|Napata (Jebel Barkal)|18.53527|31.83038
S|Nappigi (Manbij)?|36.52829|37.95515
S|Narmouthis (Madinat Madi el-Gharbiyyah)|29.18996|30.64172
S|Naṣibina / Nisibis (Nusaybin)?|37.06833|41.21437
S|Nathû / Lentopolis (Tell el-Yahudiya)|30.29210|31.33084
S|Naukratis (Kom Ge'if)|30.89485|30.59343
S|Nawali / Nabula (Girnavaz)|37.10507|41.23048
S|Nekheb (El-Kab)|25.11978|32.79797
S|Nereb (Neirab)?|36.17750|37.22708
S|Nerebtum (Ishchali)|33.30359|44.58275
S|Nihi / Niya? (Qal'at el-Mudiq)|35.41986|36.39227
S|Nina (Surghul / Ishan Durghul)|31.37763|46.49431
S|Nineveh (Tell Kuyunjik)|36.35929|43.15199
S|Nippur (Nuffar)|32.12655|45.23018
S|Nisa|37.95148|58.21128
S|Nishapur (Qohandez)|36.17094|58.84734
S|Ombos / Nubt (Kom Ombo)|24.45242|32.92866
S|Ombos / Nubt (Naqada)|25.97466|32.73319
S|Ostrakine (Tell Athar el-Filusiyyat)|31.11685|33.43086
S|Oxyrhynchus / Pr-Medjed (El-Bahnasa)|28.53871|30.65624
S|Padakku (Ha'it)|25.98033|40.47445
S|Paneas / Caesarea Philippi (Banias)|33.24767|35.69310
S|Panephysis (Manzala)|31.15594|31.93599
S|Pappa / Paphos (Kouklia)|34.70798|32.57386
S|Parsa / Persepolis (Takht-i Jamshid)|29.93482|52.89029
S|Pasargadae|30.19850|53.17334
S|Pašime (Tell Abu Sheeja)|32.39425|47.14804
S|Pella|40.75954|22.51817
S|Pelusion (Tell el-Farama)|31.04185|32.54105
S|Per-Atum Tukw / Pitom / Heroonpolis (Tell el-Maskhuta)|30.55466|32.09949
S|Pergamon (Bergama)|39.13087|27.18431
S|Petra|30.32859|35.44795
S|Phaistos|35.05129|24.81397
S|Pihilu / Pella (Khirbet Fahl)|32.45009|35.61303
S|Pitru? (Tell Aushariye)|36.65998|38.07561
S|Psenemphaia (Kom Turuga)|30.96328|30.17466
S|Pum Nahara? (Ishan Zambit H592)|32.51601|45.28493
S|Puzriš-Dagan (Drehem H1001)|32.05935|45.29243
S|Qadeš (Tell Nebi Mendo)|34.55557|36.51879
S|Qadumu? (Qatma)|36.58476|36.96524
S|Qal'at Sim'an|36.33399|36.84418
S|Qanû (Qanawat)|32.75561|36.61703
S|Qarnina / Qarnaim (Shaykh Sa'ad)?|32.83750|36.03581
S|Qarqar (Tell Qarqur)|35.74203|36.33052
S|Qatara / Zamahe (Tell Rimah)|36.25677|42.45019
S|Qatna (Tell Mishrifeh)|34.83448|36.86609
S|Qedeš (Tel Qedesh)|33.11312|35.52869
S|Rablê (Tell Zira'at / Ribla)|34.45957|36.57248
S|Raphaneae|34.94097|36.39750
S|Rapihu (Rafah)?|31.29714|34.24384
S|Rehob (Tel Rehov / Tell es-Sarem)|32.45663|35.49807
S|Rusai URU.TUR (Bastam)|38.88619|44.95028
S|Rusahinili (Toprakkale)|38.50998|43.40640
S|Rusahinili Eidurukai (Ayanis / Ağartı)|38.70835|43.21125
S|Sa / Sais (Sa el-Hagar)|30.96275|30.76725
S|Šadikanni (Tell 'Ajaja)|36.20810|40.72067
S|Šaduppûm (Tell Harmal)|33.30978|44.46658
S|Saggaratum? (Tell Abu Ha'it)?|35.25070|40.55713
S|Šakmu / Shechem (Tell Balata)|32.21324|35.28252
S|Sam'al (Zincirli)|37.10310|36.67788
S|Samarra|34.20585|43.87963
S|Samerina / Shomron / Samaria|32.27633|35.18930
S|Samuha (Kayalıpınar)|39.62113|36.52823
S|Šapinuwa (Ortaköy)|40.25416|35.23697
S|Sapiratum (Bijan)|34.30254|42.12549
S|Ṣapuna / Ṣafon (Tell es-Sa'idiyeh)|32.26758|35.57687
S|Sardes (Sartmustafa)|38.48524|28.04137
S|Sardurihinili (Çavuştepe)|38.35300|43.46129
S|Ṣariptu / Sarephtha (Ras el-Qantara)|33.46430|35.29517
S|Šarišša (Kuşaklı)|39.30843|36.90967
S|Scaphae / Lower Uskaf? (Tulul el-Shu'ailah D826)|32.95395|45.10750
S|Set Maat (Deir el-Medina)|25.72805|32.60135
S|Šehna / Šubat-Enlil (Tell Leilan)|36.95853|41.50627
S|Seleukia Pieria|36.11705|35.93815
S|Seleukia (Tell Omar)|33.09876|44.52329
S|Seleukia / Zeugma|37.05517|37.86948
S|Seleukia (Silifke)|36.37667|33.91568
S|Sergilla|35.67094|36.58326
S|Sergiopolis (Resafa)|35.62910|38.75795
S|Shabwa|15.36900|47.02552
S|Shiloh (Tell Shiloh / Khirbet Seilun)|32.05617|35.28988
S|Šibaniba (Tell Billa)|36.43376|43.34825
S|Sidon|33.56243|35.36933
S|Sikanu (Tell Fekheriye)|36.84261|40.06983
S|Silluwa? / Salamis (Konstanteia)|35.18558|33.89933
S|Sinabu? (Murattaş / Pornak)|37.79684|40.37923
S|Singara (Balad Sinjar)|36.32705|41.85796
S|Sippar-dūrim (Tell ed-Der)|33.09812|44.29949
S|Sippar-ṣērim (Abu Habba)|33.06000|44.25466
S|Siyannu (Tell Siyanu)|35.36540|36.00296
S|Smabehdet / Paiuenamon (Tell el-Balamun)|31.26017|31.57244
S|Smyrna (Izmir)|38.41876|27.13886
S|Soknopaiou Nesos (Dimai)|29.53403|30.66917
S|Šuksu (Tell Sukas)|35.30587|35.92274
S|Ṣumur / Ṣimirra (Tell Kazel)|34.70849|35.98614
S|Ṣupru? (Tell Abu Hasan)|34.65440|40.88514
S|Sura / Suriya|35.89693|38.77896
S|Suru? (Sur Telbis)|34.37549|42.04610
S|Šuruppak (Fara)|31.77763|45.50975
S|Susa|32.18977|48.25205
S|Šušarra (Tell Shemshara)|36.20071|44.93825
S|Ṭabatu (Tell Ta'ban)|36.33621|40.78773
S|Tadmur / Palmyra|34.54741|38.27364
S|Tahazimuna? / Dazimon (Tokat)|40.31741|36.54901
S|Taidu? (Tell Hamidiya)|36.81603|41.16503
S|Takritain (Tikrit)?|34.60323|43.69231
S|Tamesu / Tamassos (Politikou)?|35.02935|33.24633
S|Taʿnak (Taʿannach)|32.52193|35.21950
S|Tanis (San el-Hagar)|30.97590|31.88378
S|Tapigga (Maşat Höyük)|40.14830|35.76232
S|Tarbiṣu (Sharif Khan)|36.40867|43.07743
S|Tarhuntašša? (Kızıldağ)?|37.49331|33.07420
S|Tarsa / Tarsos (Gözlü Kule)|36.91242|34.89592
S|Tawiniya / Tavium (Büyüknefes)|39.85798|34.50610
S|Tayma|27.62683|38.54953
S|Tebtunis (Tell Umm el-Baragat)|29.10813|30.76176
S|Teišebai URU (Karmir-blur)|40.15359|44.45270
S|Tentyris (Dendera)|26.14123|32.66987
S|Terenuthis (Kom Abu Billo)|30.42792|30.81361
S|Terqa / Sirqu (Ashara)|34.92225|40.56841
S|Thebe / Waset / Nut|25.70837|32.64734
S|Tiberias|32.78642|35.54226
S|Tidu? (Üç Tepe / Kurkh)|37.82614|40.53988
S|Til-Abnu? (Tell Qitar)|36.38354|38.18029
S|Til-Barsip / Masuwari (Tell Ahmar)|36.67443|38.12095
S|Til-Bašerê? (Tilbeşar)|36.87278|37.55931
S|Timnah? (Tel Batash)|31.78448|34.91100
S|Timna'|15.01919|45.80467
S|Tiryns|37.59915|22.80029
S|Tripolis|34.45076|35.81365
S|Troy / Wilusa (Hisarlik)|39.95752|26.23830
S|Tu'ammu? (Tuwwama)|36.19351|36.81092
S|Ṭuba? (Umm el-Marra)|36.13403|37.69347
S|Tunip? (Asharneh)|35.28390|36.39936
S|Tušhan (Ziyaret Tepe)|37.79324|40.79327
S|Tušpa (Van)|38.50239|43.33929
S|Tuttul (Tell Bi'a)|35.95770|39.04765
S|Tutub (Khafaja)|33.35566|44.55556
S|Tuwanuwa / Tuhana / Tyana (Kemerhisar)|37.82271|34.57022
S|Tyre (Sur)|33.27029|35.19597
S|Ugarit (Ras Shamra)|35.60212|35.78557
S|Ukhaidir|32.43950|43.60265
S|Umma (Tell Jokha)|31.66743|45.88768
S|Upî? (Tulul Mujaili' D590)|33.18405|44.70127
S|Ur (Tell Muqayyar)|30.96180|46.10512
S|Urkeš (Mozan)|37.05771|40.99640
S|Uruk (Warka)|31.32263|45.63961
S|Uskaf bani Junayd (Sumaka D734)|33.09105|45.03737
S|Veh Ardashir / Choche (Tell Baruda)|33.09823|44.55336
S|Wasit|32.18618|46.29969
S|Zabalam (Tulul Ibzaikh)|31.74473|45.87575
S|Zaḫiku? (Kemune)|36.76449|42.73266
S|Zalpah (Tell Hammam et-Turkman)|36.48254|39.05698
S|Zaralulu (Tell ed-Diba'i)|33.32276|44.48194
S|Zenobia (Halabiye)|35.68925|39.82202
S|Zinzar (Qal'at Shaizar)|35.26566|36.56644
S|(A062)|33.04094|44.43723
S|(A063)|33.00766|44.36712
S|(A064)|33.00491|44.28930
S|(A067?)|32.97431|44.33662
S|(A068)|32.96000|44.35494
S|(A076)|32.82798|44.41498
S|(A079)|32.76458|44.48804
S|(A100)|32.86958|44.51889
S|(A107)|32.85579|44.52963
S|(A108)|32.84746|44.53596
S|(Abar Yafa H604)|32.42237|45.33186
S|(Abbas el-Kurdi)|31.31179|45.90105
S|(Abdul Karim)|33.60064|44.36455
S|('Aberta D620)|33.23908|44.88040
S|(Aboo Amoud Nejat)|31.74585|48.84639
S|(Abu Bezooneh K135)|32.54872|44.51747
S|(Abu Biyariq K57)|32.61931|44.71182
S|(Abu Dhahab)|31.81312|44.52419
S|(Abu Drikha)|36.03049|37.48569
S|(Abu Fanduweh KS 59)|32.09428|48.31637
S|(Abu Halefiah)|33.04443|44.54135
S|(Abu Hasan / Ishan Imru'ah K142)|32.47110|44.55383
S|(Abu Hatab K161)|32.52713|44.75197
S|(Abu Hejjil K120)|32.62876|44.42509
S|(Abu Jrein)|36.04887|37.45347
S|(Abu Kula)|36.66708|42.32761
S|(Abu Lehid)|33.07039|44.55218
S|(Abul Hani K119)|32.63902|44.42319
S|(Abu Ma'lak)|33.14495|44.32540
S|(Abu Qadir)?|33.89403|45.24137
S|(Abu Qubur A053)|33.14529|44.21749
S|(Abu Rotham K115)?|32.65526|44.39975
S|(Abu Ruyah)|30.81843|46.80370
S|(Abu Salabikh)|32.25225|45.05330
S|(Abu Salabikh K85)|32.54191|44.81403
S|(Abu Shellil K134)|32.54755|44.50906
S|(Abu Sudaira K47)|32.53351|44.63243
S|(Abu Suraydib K164)|32.56748|44.72422
S|(Abu Taraichiyah K84)|32.55605|44.83770
S|(Abu Turfeh K133)|32.54601|44.50139
S|(Abu Wajnam)|36.68434|42.62524
S|(Abu Zura)|32.10119|46.65878
S|(Abujerd)|36.08435|43.60394
S|(Adjeser)|36.80116|44.63240
S|(Aǧil Teppe)|37.64727|45.23129
S|(Ahmed)|35.27474|36.44242
S|(Ahmedabad / Oujteppe?)|34.60196|48.98466
S|('Ain el-Funaidiq)|36.18181|36.37031
S|('Ain Ghazal)|31.98696|35.97647
S|('Ain Tell)|35.81818|36.33017
S|('Ain Zelal)|35.73178|36.43364
S|(Akarçay Höyük)|36.91743|38.01707
S|(Akarçay Tepe)|36.91888|38.02561
S|(Akçemezraa)|36.80860|37.57702
S|(Akhtarina)|36.51421|37.33807
S|(Akpınar Höyük)|36.43304|36.52841
S|(Aktepe)|37.72463|40.56996
S|(Alaçahöyük)|40.23453|34.69526
S|(Alahan)|36.66399|37.43737
S|('Alan Teppe)|35.28374|45.76856
S|(Alazlı)|38.69392|41.82469
S|(Ali Kosh)?|32.55779|47.32475
S|(Ali Pasha)|34.35180|45.02895
S|(Ali Şama Höyük)|37.15094|42.36480
S|(Al-Khidr)|29.46571|48.28809
S|(Al-Sayal)|34.59711|40.90969
S|(Altintepe)|39.69631|39.64661
S|(Altıntoprak)|37.11178|40.60390
S|(Altyn Depe)|36.85813|60.43243
S|(Amara West)|20.82156|30.38471
S|(Amarsava Höyük)|37.17213|42.38205
S|('Ammourin)|35.32192|36.38059
S|('Amr Khan)?|36.19344|43.34230
S|('Anz)|32.40441|36.68708
S|(Apsarı)|38.39823|31.54263
S|('Ar)|35.48511|36.67946
S|('Arab)|37.06595|40.88856
S|('Arab el-Mulk)?|35.26514|35.92563
S|(Aramus)|40.24908|44.65190
S|(Arisman I)|33.65177|51.97662
S|(Arjan)?|30.65867|50.27308
S|(Arkub Tell Khattab)|32.96850|44.65262
S|(Aruchlo 1)|41.45331|44.69553
S|(Aruchlo 2)|41.45274|44.69215
S|(Aşağıbeğdeş)|36.81445|38.91956
S|(Aşağıderen)|36.76607|39.02109
S|(Aşağıoylum)|36.86384|38.54351
S|(Aşvan Kalesi)?|38.89225|38.93682
S|(Ayia Triadha)|35.05925|24.79264
S|('Ayn Hassan)|36.05806|37.21960
S|(Ayvalıpınar)|40.46118|35.64900
S|(Aşağıalınca)|37.41399|39.52281
S|(Aşağı Anzaf)|38.56787|43.46422
S|(Aşağıryarımca)|36.89509|38.96909
S|(Aşağı Salat)|37.81771|40.91870
S|(as-Sila'?)|30.78403|35.57793
S|(Atlit Yam)|32.70932|34.93699
S|('Avdat)|30.79441|34.77356
S|('Awas)|32.46917|36.77231
S|('Awena)|36.06118|43.69625
S|('Ayoun)|35.26955|36.52119
S|(Ayyelet ha-Shahar)|33.02132|35.57611
S|('Azam Foqani)|36.89959|40.83445
S|(Aznavur)|37.08305|41.51623
S|(Bab)|36.36923|37.50719
S|(Baba Jan Teppe)|34.02046|47.93310
S|(Bab edh-Dhra')|31.25322|35.53319
S|(Bab-w-Kur)|36.16341|44.89781
S|(Baghuz 1)|34.47563|40.97739
S|(Baghyalat Umm el-Roz)|31.96646|46.57073
S|(Bakacık)|37.14407|41.60093
S|(Bakirte)|35.55681|43.56029
S|(Balkat)|36.86948|38.99305
S|(Banaat el-Hassan)|31.55407|45.54273
S|(Bandian)|37.46310|59.10164
S|(Banura)|32.28719|45.56919
S|(Baqalou)|35.39430|36.39753
S|(Bara)|35.68414|36.54083
S|(Baragiti)|35.76396|37.04391
S|(Barbar)|26.22616|50.48411
S|(Bardastee)|36.20310|44.93450
S|(Bard-e Nechandeh)|32.03521|49.33448
S|(Bash Teppe)|35.88104|44.00659
S|(Basorin)|37.15179|42.34429
S|(Bassouta)?|36.43352|36.87035
S|(Basta)|30.22757|35.53355
S|(Bavian canal head)|36.76156|43.41999
S|(Bayraklı)|38.46422|27.17019
S|(Bazyan)|35.63737|44.97263
S|(Behbeit el-Hagar)|31.02798|31.28813
S|(Beisamoun)|33.09379|35.57967
S|(Bektaş)|37.12439|40.44093
S|(Bellitaş)|36.91657|39.12495
S|(Bergul el-Buz)|36.69255|40.69657
S|(Bestansur)|35.37686|45.64554
S|(Beycesultan)|38.25668|29.70079
S|(Bikasi 2)|32.12716|44.63180
S|(Binaj Baj SRP 19)|34.44540|45.13164
S|(Bin Gerd-i Muan)|35.37722|45.71499
S|(Biret Armanaz)?|36.04772|36.48047
S|(Birkhanis)|37.00245|40.50246
S|(Birkleyn / Tigris Tunnel)|38.52966|40.54765
S|(Bir 'Ugla)|36.87263|42.18513
S|(Bismah / Khor Umm el-Baid K110)|32.59835|44.82175
S|(Bismaya D562)|33.23511|44.60339
S|(Bisnada)?|35.54707|35.80184
S|(Bokha)|36.59133|42.38349
S|(Bolvadin Üçhöyük)|38.69286|31.03686
S|(Bozhöyük)|36.61698|36.46398
S|(Bozhüyük)|37.07776|40.22653
S|(Boztepe)|37.84130|40.77890
S|(Boztepe)|36.97800|38.48315
S|(Bugga Ishan KS 49)|32.13038|48.44031
S|(Buq'ata)??|33.19853|35.78612
S|(Burj Agdal)|36.40878|36.84445
S|(Buwayda)|35.14296|37.04534
S|(Buwayyir)|37.01824|41.40838
S|(Büyücek)|36.78207|38.99132
S|(Büyükboğaziye)|36.96597|40.29742
S|(Büyüktepe)|37.14551|40.51390
S|(Çaǧıl)|37.12124|40.67841
S|(Çamlıdere)|37.15561|39.06441
S|(Çamurlu)|36.65974|37.47483
S|(Çatak)|37.17019|40.68633
S|(Çatalhöyük)|37.66633|32.82797
S|(Çatal Höyük)|36.29765|36.54539
S|(Çayönü)|38.21872|39.72882
S|(Çaytepe)|38.21074|40.50782
S|(Chemchemal)|35.53686|44.83477
S|(Cheshmeh Ali)|35.60760|51.44589
S|(Chogha Bonut)|32.22268|48.50436
S|(Chogha Gavaneh)|34.11033|46.52878
S|(Chogha Mami)?|33.78137|45.53752
S|(Chogha Mish)|32.22315|48.55463
S|(Chogha Pahn)|32.22909|48.61323
S|(Chogha Pahwandeh KS 165)|32.18457|48.68493
S|(Cholama Fawqani)|36.88012|40.74193
S|(Cholama Tahtani)|36.82310|40.78682
S|(Çiftlik)|36.81413|37.81365
S|(Çingentepe)|36.48057|33.54788
S|(Coba Hüyük / Sakça Gözü)|37.20128|36.90585
S|(Çobaktepe)|37.36562|36.92978
S|(Çorten)|36.76993|37.27291
S|(D114)|33.67498|44.52316
S|(D253)|33.46163|44.78781
S|(D601)|33.18681|44.73807
S|(Dadikh)|35.80285|36.73638
S|(Daginod Tepe)|35.09774|44.13598
S|(Dar'a)?|32.61974|36.09762
S|(Darband-i Gaur relief)|35.21862|45.41327
S|(Darisiat el-Kabir)|36.78771|41.28386
S|(Daskyleion)|40.13277|28.05068
S|(Dayr Ayyub)|37.09689|41.70810
S|(Dayr Khabiya)|33.36140|36.16117
S|(Dayr Sim'an)|36.32654|36.83596
S|(Dayr Sras)|33.04592|35.68116
S|(Dayr Una Agha)|37.10756|41.80288
S|(Dederiyeh Cave)|36.39905|36.86768
S|(Değirmen Höyük)|36.87098|38.04910
S|(Deh-e Now?)|34.10093|48.06141
S|(Deinit)|35.89416|36.67392
S|(Demirkapı)|37.05673|40.46275
S|(Devehüyük)|36.75574|37.73563
S|(Dhibin)|32.43853|36.56414
S|(Dibak Teppe)|35.42947|44.27439
S|(Dibbin)|31.89728|45.66096
S|(Dibsi Faraj)|35.92660|38.22882
S|(Dikmen)|37.09039|40.41258
S|(Do Ger)|37.03489|41.49451
S|(Dholavira)|23.88762|70.21410
S|(Dolatabad)|31.83301|49.00394
S|(Domuztepe)|37.29010|36.25466
S|(Douabiq)|36.56408|37.27479
S|(Doubbeine)|35.28157|36.37913
S|(Dourou)|35.27662|36.48904
S|(Dubai)|32.85066|44.67252
S|(Dugirdkhan)|36.15484|44.84742
S|(Duknuk)?|36.79212|37.91106
S|(Duruca / Gertwin)|37.09344|41.30832
S|(E34)|30.96873|45.78892
S|(E156)|30.92242|45.88452
S|(Ed-Dem)|36.07014|44.96069
S|(Eflatun Pınar)|37.82554|31.67463
S|(Eǧriköy / Yeşilova)?|38.22208|35.21382
S|('Ein Gev / Khirbet el-'Asheq)?|32.78406|35.63755
S|(El-Akkar el-Kabir)|31.32332|47.08497
S|(El-Andalus / Tell Abu Khadraf)|36.62358|41.61453
S|(Elbeğendi)|37.30572|39.58643
S|(Elgün)|37.17008|39.82874
S|(El-Homor)|31.43167|45.30988
S|(Elifoğlu)|36.95140|37.98248
S|(El-Judafia)|33.95024|42.56089
S|(El-Karak)|31.18130|35.70171
S|(El-Khan)|34.11542|42.39212
S|(El-Khanzara)|31.61969|45.75187
S|(El-Khatre)|35.74293|36.93957
S|(El-Kowm)|35.19203|38.85810
S|(El-Makhtaraq)|32.52451|44.37176
S|(Elmalı)|36.88395|37.36767
S|(El-Mina)|36.06159|35.97415
S|(El-Muadak?)|31.24982|47.16152
S|(El-Mudayfir D409)|33.35604|45.26175
S|(El-Qrayya)?|33.53908|35.41738
S|(El-Ra'i)|36.61331|37.44985
S|(El-Rawda)|35.18102|37.63286
S|(Enkomi)|35.16557|33.87044
S|(EPAS 29)|35.99131|43.87256
S|(EPAS 30)|35.99281|43.86838
S|(EPAS 33)|36.09875|43.77361
S|(EPAS 36)|36.09771|43.77002
S|(EPAS 39)|36.10418|43.76690
S|(EPAS 43)|36.10135|43.77230
S|(EPAS 86)|36.10194|43.79443
S|(EPAS 87)|36.09642|43.77874
S|(Er-Rubba)|35.13122|36.97906
S|(Esen Tepe)|36.46105|36.42778
S|(Eshkaft-e Salman)|31.81680|49.84744
S|(Eskiyapar)|40.15798|34.77286
S|(Es-Sadidiya)|36.85411|42.10701
S|(Es-Safa)|36.94467|41.83490
S|(Eṣ-Ṣaila')|32.41685|44.41164
S|(Et-Tar)|32.48188|43.77945
S|(Et-Tell)|31.91663|35.26127
S|(Et-Tell)|32.91031|35.63067
S|(Et-Tine)|31.39468|45.61305
S|(Eynan / 'Ain Mallaha)|33.07405|35.58134
S|(Eyüpnebi)|37.36105|39.64356
S|(Ezbet el-Jizawi)|30.86021|30.39828
S|(Fanagorii͡a)|45.27639|36.95938
S|(Fara)|35.44640|43.47017
S|(Farit)|32.39146|44.26482
S|(Furuncu Tepe)|38.33268|38.45445
S|(Gaida)|34.97006|44.29128
S|(Ganaus)?|35.65608|43.26330
S|(Ganj Nameh)?|34.75628|48.43828
S|(Gavur Kalesi)|39.53131|32.55928
S|(Gawr Teppe)|34.54587|45.32116
S|(Gaziantep)|37.06619|37.38332
S|(Geoy Teppe)|37.51820|45.14506
S|(Gera Zil Ṣaghir)|36.78247|41.05057
S|(Ger Balwiya)|36.20779|41.81692
S|(Ger Bazan)|36.81129|40.84440
S|(Ger Bejnik Faouqani)|36.76020|40.93982
S|(Ger Bir)|36.90201|42.39209
S|(Gerchal)|36.71600|42.52862
S|(Gerd 'Adul 'Aziz)|36.10404|43.89609
S|(Gerd 'Ali Agha)?|36.44593|43.80865
S|(Gerd 'Azaban)|36.00551|43.83242
S|(Gerde Ṣefe)|35.28822|45.97940
S|(Gerde Resh)|35.38454|45.60611
S|(Gerdi Shakar)|35.26685|45.84517
S|(Gerdi Shamlu)|35.28707|45.87420
S|(Gerd-i Qalrakh)|35.35339|45.83559
S|(Gerdi Qawagh EPAS 180)|36.14797|43.69177
S|(Ger Diwan)|36.91492|41.05147
S|(Gerd Oso)|36.80840|40.80752
S|(Gerd Qaburstan EPAS 31)|35.98877|43.86301
S|(Gerd Surezha EPAS 27)|35.99859|43.88521
S|(Ger el-Khan)|36.53862|41.58477
S|(Ger-e Pan)|36.77578|42.93554
S|(Ger Gariya)?|32.37575|47.11504
S|(Ger Ghanishan)|36.81303|40.89725
S|(Ger Hassar)|36.94013|40.88155
S|(Gerhok)|36.93309|41.89925
S|(Gerkafir)|36.68532|42.51861
S|(Gerke Jiyuk Kabir)|36.09855|41.62943
S|(Ger Kharaz)|36.23144|41.79986
S|(Ger Kidish)?|36.10744|41.57375
S|(Ger Kut)|36.84520|41.04828
S|(Ger Lawand)|36.81931|42.33647
S|(Ger Mahir)|36.87224|40.85437
S|(Ger Matbakh)|36.87393|42.51423
S|(Ger Matlu)|36.90050|40.90647
S|(Ger Sawwar)|36.99647|41.44183
S|(Ger Senli)|36.66083|37.53633
S|(Ger Sheran)|37.00775|41.52601
S|(Ger Zawri?)|36.82204|38.48024
S|(Ger Zediy)|37.21165|42.26066
S|(Ger Zil Kabir)|36.83110|41.08261
S|(Gezira Abu Mitawi)|30.88640|31.78920
S|(Gezira Abu Umran)|30.85732|31.70425
S|(Ghar-i Kamarband)?|36.68886|53.49762
S|(Ghasaniya)|37.10988|41.90508
S|(Ghergouz K41)|32.59304|44.63061
S|(Gird-i Rostam)|35.75296|45.91568
S|(Girmeli / Ger Ermira)|37.11468|41.42737
S|(Glei'eh)|34.29282|42.20483
S|(Göbekli Tepe)|37.22322|38.92247
S|(Godin Teppe)|34.51842|48.06840
S|(Gohar Teppe)|36.67870|53.40021
S|(Gohbal)?|36.51542|41.95913
S|(Gök Teppe)|35.84851|44.83290
S|(Göllüdağı)|38.25980|34.55066
S|(Göllühöyük)|37.37663|36.90559
S|(Gonur Tepe)|38.21378|62.03778
S|(Götübüyük)|36.23730|36.43117
S|(Goytepe)|40.97020|45.70508
S|(Gözegöl)|37.98439|40.05185
S|(Grai Resh)|36.31814|41.91907
S|(Gre Dimse)|37.82753|40.96629
S|(Gre Virike)|36.92259|38.01533
S|(Gritelle)|37.56626|38.57043
S|(Gubba)|31.04156|46.97144
S|(Gurban Tepe)|40.89416|46.24943
S|(Gürkaynak)|37.11260|41.62805
S|(Gurga Chiya)|35.21350|45.92120
S|(Gurob)|29.20105|30.95064
S|(Güzlek)|37.20384|39.81357
S|(H555)|32.50920|45.19683
S|(H614)|32.40964|45.39695
S|(H863)|32.25568|45.43999
S|(H1116)|32.20085|45.50355
S|(H1114)|32.20742|45.49481
S|(H1115)|32.21192|45.50984
S|(H1188)|32.08119|45.48428
S|(H1352)|31.97158|45.33386
S|(H1382)|31.75381|45.33157
S|(Habite)|35.44003|36.53767
S|(Habuba Kabira South / Qannas)|36.15016|38.06082
S|(Hacinebi Tepe)|37.05960|37.97522
S|(Hadir)|35.98749|37.04307
S|(Haftavan Teppe)|38.16703|44.79300
S|(Hajji Firuz Teppe)|36.99466|45.47428
S|(Hajji Yunus)|36.37441|42.33141
S|(Hakemi Use)|37.80306|40.74289
S|(Hala Sultan Teke)|34.88673|33.60452
S|(Halhul)|31.82708|44.64386
S|(Halkalı)|37.14829|40.59041
S|(Hamad Agha el-Kabir)|36.81795|42.37835
S|(Hamad Agha es-Saghir)|36.81734|42.42013
S|(Hamara)|36.90004|41.48793
S|(Hamide)|35.95582|37.10707
S|(Hamüs)|36.96435|37.73446
S|(Hanawija)?|33.22093|35.28230
S|(Ḥannawiya)|37.10169|42.12237
S|(Hannjour)|35.18947|36.47156
S|(Hansa / Zaki el-Kebir)|36.64976|41.41996
S|(Harappa)|30.62694|72.86790
S|(Harim)|36.20724|36.51910
S|(Hasada Fawqani)|37.10844|40.98886
S|(Hasanlu)|37.00459|45.45890
S|(Hasantepe)|37.12721|41.49277
S|(Haveh / Aveh)?|34.79957|50.42926
S|(Hawahöyük)|36.60024|37.67026
S|(Hawarte)|35.51667|36.43251
S|(Hazar Mard)?|35.50488|45.32655
S|(HB1)|33.13681|44.23551
S|(HB2)|33.12949|44.24926
S|(HB3)|33.12604|44.26004
S|(HB5)|33.11830|44.27826
S|(HB6)|33.13506|44.29383
S|(Heit el-Ghurab)|29.97114|31.14132
S|(Hejeil)|32.38874|44.32497
S|(Helawa)|35.99933|43.78847
S|(Hish)|35.54242|36.64474
S|(Hilala K75)|32.58201|44.77625
S|(Hilala K76)|32.57853|44.78406
S|(Hili)|24.29258|55.79393
S|(Hirba Jarura)|33.62523|42.78646
S|(Hirbemerdon Tepe)|37.77823|41.01365
S|(Hirmil)?|34.39295|36.39488
S|(Homat Kale)|37.93372|31.32783
S|(Horbat Tevet)|32.63780|35.33381
S|(Horom)|40.65629|43.89981
S|(Houash)|35.44256|36.46053
S|(Houaid)?|35.27944|36.46452
S|(Humairé)|34.62830|36.07762
S|(Hümaniz)|37.04945|37.42266
S|(Hurria)|32.09310|44.54411
S|(Husain Fattah)?|35.23944|45.87220
S|(Hussein Teppe)|36.30728|43.49918
S|(hut village)|25.73624|32.60093
S|(Hwislat)|31.54574|44.93507
S|(Ibn Habib)|32.36565|44.27705
S|(Ibrahem)|30.99320|46.23622
S|(Ibrahim)|31.83014|44.56639
S|(Ibrahim Bayis)|35.77406|43.55472
S|(Ikiztepe)|41.61358|35.87025
S|(Imam 'Abbas A249)|32.28211|44.74159
S|(Imam 'Abdalla)|31.43773|44.82765
S|(Imam Ajil)|32.19854|44.63136
S|(Imam Haj Yusuf)?|33.68135|45.49791
S|(Imam Idris)|31.68290|45.03168
S|(Imam Jadir)?|34.04334|44.11069
S|(Imam Mjyheal)|31.42428|45.31587
S|('Imar)|36.30808|36.44722
S|(Isham)|32.89412|44.27677
S|(Ishan)|32.68429|44.39860
S|(Ishan)|31.67623|45.03308
S|(Ishan Abr Kharaz)|31.59726|46.19920
S|(Ishan Abr Taraba)|31.50555|46.05288
S|(Ishan Abu 'Ajaj)|32.73109|44.00585
S|(Ishan Abu 'Amud A054)|33.11868|44.19662
S|(Ishan Abu Basur esh-Sharqi H875)|32.27620|45.48784
S|(Ishan Abu Diyyayyat KS 4)|32.16158|48.49229
S|(Ishan Abu edh-Dhahab)|31.36521|46.52081
S|(Ishan Abu Gharib)|31.08564|46.03901
S|(Ishan Abu Guraib)|32.45931|46.15135
S|(Ishan Abu Hadidah)|31.06663|46.10096
S|(Ishan Abu Ḥaṣawa)|31.54718|47.32876
S|(Ishan Abu Hatab)|32.65961|44.87281
S|(Ishan Abu Jasib A258)|32.30935|44.99286
S|(Ishan Abu Judu)|32.46985|45.14959
S|(Ishan Abu Khalal)|31.38535|45.09526
S|(Ishan Abu Kumbaru)|31.05288|46.19629
S|(Ishan Abu Maktum)|31.57618|45.26303
S|(Ishan Abu Qabr)|32.69289|44.82736
S|(Ishan Abu Riḥa)|31.31645|46.13198
S|(Ishan Abu Rukba)|31.71177|46.51945
S|(Ishan Abu Saba)|32.91296|44.63916
S|(Ishan Abu Saba')|31.33011|46.07880
S|(Ishan Abu Ṣaba')|31.53304|46.43898
S|(Ishan Abu Ṣafi)|32.49605|46.17203
S|(Ishan Abu Salir)|31.31974|45.37443
S|(Ishan Abu Shajar)|31.17560|46.73659
S|(Ishan Abu Shawar)|31.90391|44.85575
S|(Ishan Abu Tarbaka)|32.12499|44.69932
S|(Ishan Abu Tubairah)|30.98308|46.26766
S|(Ishan Abu Umayma)|32.10627|44.62483
S|(Ishan 'Afaṣ)|31.35717|45.13533
S|(Ishan Ahmer)?|31.42808|45.05700
S|(Ishan 'Alirah)|31.31443|46.05461
S|(Ishan Angur Zuraybah A135)|32.81962|44.75034
S|(Ishan Aqar)|31.09909|45.50707
S|(Ishan Barghuthiat)|32.73848|44.79397
S|(Ishan Bayt H1383)|31.75588|45.33575
S|(Ishan Dakhkhak)|32.71073|44.83525
S|(Ishan Daliya)|31.48164|47.36771
S|(Ishan Daud K104)|32.62756|44.83501
S|(Ishan Dhiniyat)|31.77367|45.01044
S|(Ishan Dijat)|31.76275|46.51781
S|(Ishan ed-Dowweh)|31.80465|48.91232
S|(Ishan ed-Dura)|31.57857|46.47221
S|(Ishan el-Ahimar H1360)|31.88763|45.24176
S|(Ishan el-Fitr)|31.57894|45.96864
S|(Ishan el-Hadabiyat)?|32.37358|46.18531
S|(Ishan el-Hamar?)|32.70245|44.39607
S|(Ishan el-Hamir)?|31.62382|44.77153
S|(Ishan el-Hamza)|31.73300|44.95466
S|(Ishan el-Hawizi)|32.10518|46.65343
S|(Ishan el-Hiba es-Saghir)|31.41874|46.39830
S|(Ishan el-Jamba)|31.99099|45.10364
S|(Ishan el-Jamda)|31.30589|46.67116
S|(Ishan el-Jihariz H656)|32.35214|45.09393
S|(Ishan el-Kaba)|31.57587|46.22966
S|(Ishan el-Khamriya)|32.09929|46.69258
S|(Ishan el-Kharah K70)|32.53881|44.77654
S|(Ishan el-Khazna K25)|32.55397|44.56936
S|(Ishan el-Khor H534)|32.38771|45.07464
S|(Ishan el-Malah)|32.52126|44.30860
S|(Ishan el-Warash)|32.53072|44.31087
S|(Ishan el-Wa'y H517)?|32.43245|45.05843
S|(Ishan es-Sabusiya)|31.68250|44.68591
S|(Ishan es-Sadirat)|31.99603|46.35324
S|(Ishan al-Sama‘a)|32.07226|45.41930
S|(Ishan es-Saraijiya)|32.72757|44.45868
S|(Ishan et-Tawil)|31.57220|46.24049
S|(Ishan eṭ-Ṭawila)|31.84953|46.85624
S|(Ishan ez-Zalali)|32.55929|44.26313
S|(Ishan ez-Zubiya)|31.58864|46.61231
S|(Ishan Faras)|31.83287|46.57574
S|(Ishan Guraymis)?|32.01791|46.15779
S|(Ishan Hamid A166)|32.80525|44.80316
S|(Ishan Hamid A101)|32.86306|44.52521
S|(Ishan Huraizeh K62)|32.62956|44.78095
S|(Ishan Husayn)|32.69970|44.93398
S|(Ishan Ibn Hassan K141)|32.49030|44.55665
S|(Ishan Imayrin)?|32.26856|46.28457
S|(Ishan Ishmarbab)|32.79364|44.33403
S|(Ishan Jal'a Hilal)?|31.64842|45.23556
S|(Ishan Jun)|31.95437|46.38226
S|(Ishan Juwi)|31.07468|45.75396
S|(Ishan Kaffa / Ishan Zuraybah A136)|32.81664|44.74198
S|(Ishan Karya el-Kabir)|31.81699|46.31228
S|(Ishan Karya eṣ-Ṣaghir)|31.80850|46.32636
S|(Ishan Kaṭar el-Gharbi)|31.75189|46.59450
S|(Ishan Kaṭar el-Janubi)|31.71642|46.63647
S|(Ishan Kaṭar esh-Sharqi)|31.77229|46.63254
S|(Ishan Khaiber)|31.05960|45.93257
S|(Ishan Khalfah / Tuweirij K155)|32.50965|44.71470
S|(Ishan Khalid)|31.95151|44.56520
S|(Ishan Khaṣaf)|31.18302|46.60237
S|(Ishan Madhrub H620)|32.39850|45.40917
S|(Ishan Mafshuk)|31.03474|45.95822
S|(Ishan Mahsan)|31.36661|46.07348
S|(Ishan Majirash)|32.44564|46.31754
S|(Ishan Makhr el-Iraq)|32.62689|44.92573
S|(Ishan Mal'ab)|31.32720|46.11019
S|(Ishan Matrud)|31.82248|45.39924
S|(Ishan Ma'yanaj)|31.89464|46.52168
S|(Ishan Mazdud)|32.27395|44.26152
S|(Ishan Mirzabad)|33.04409|45.76943
S|(Ishan Mizyad)|32.59322|44.55620
S|(Ishan Mudsina)|32.24404|46.21102
S|(Ishan Muhaiṣimah)|31.08540|46.16720
S|(Ishan Musawi)|31.91851|46.57815
S|(Ishan Nowaywis)|31.12352|45.53052
S|(Ishan Rabiṣa)|33.00880|44.47299
S|(Ishan Rakiba)|31.38885|46.02703
S|(Ishan Rakiba es-Sadda)|31.24604|46.75570
S|(Ishan Rishayd esh-Sherrikh A168)|32.75839|44.80025
S|(Ishan Rusiyat)|32.55720|45.27124
S|(Ishan Ṣa'biya)|31.37149|46.09324
S|(Ishan Said)|32.37375|45.26103
S|(Ishan Sayyid Riḍa H1325)|31.98078|45.15061
S|(Ishan Shahraban)|31.92662|46.42994
S|(Ishan Shall? / Tulul el-Ajjaz?)|31.58854|45.33629
S|(Ishan Shumaykhi)|31.51889|46.64767
S|(Ishan Umm el-Fak)|31.56142|46.14049
S|(Ishan Umm es-Saba'a)|31.09013|46.14840
S|(Ishan Umm Halawiyah)|31.05992|46.16946
S|(Ishan Umm Halfawiya)|31.42129|46.06773
S|(Ishan Umm Jarif)|31.77094|46.69034
S|(Ishin el-Kawira)|31.19767|46.79271
S|(Ishin el-M'ammar U079)|31.67602|45.64125
S|(Ishin el-M'ammar U092)|31.63130|45.69554
S|(Ishin el-Maṭbakat)|31.07524|45.97414
S|(Ishin esh-Shamsiya)|31.40945|46.48279
S|(Ishin Ma'ilmat)|31.19076|46.49232
S|(Istabulat)|34.08408|43.91541
S|(Ivan-e Kerkha)|32.32967|48.12302
S|(Ivriz / Aydınkent)?|37.40049|34.16657
S|(Izbet Sarta)|32.10456|34.96427
S|(Jaba'din)|33.82378|36.51233
S|(Jabbul)|36.09035|37.51943
S|(Ja'Deh)?|36.64579|38.20740
S|(Jalamah)?|36.36476|36.76407
S|(Jar'a Amtarya)|32.99814|44.33658
S|(Jar'a Umm el-Wayalad)|32.97765|44.33426
S|(Jarmo)|35.55582|44.93036
S|(Jar Sila)|35.24458|43.56479
S|(Jatırtepe)|36.97142|38.37910
S|(Jebel Aruda)|36.23431|38.09866
S|(Jebel Khalid)|36.35603|38.17498
S|(Jebel Mashtala)|34.89458|40.60783
S|(Jedideh)?|36.30373|43.22862
S|(Jekke)|36.60679|37.29512
S|(Jemdet Khisbak K124)|32.61933|44.40369
S|(Jemdet Nasr K92)|32.71796|44.77946
S|(Jemdet Suedi K45)|32.55151|44.62258
S|(Jerablus Tahtani)|36.79011|38.02116
S|(Jerahiyeh)|36.70375|43.21371
S|(Jerwan aqueduct)|36.66984|43.39334
S|(Jinjan)|30.22529|51.44656
S|(Jother)?|32.19846|44.76998
S|(Jul Bustan Tahtani)|36.83138|40.94998
S|(Judlu)|35.88231|37.59410
S|(Juya)?|33.23658|35.33881
S|(K49)|32.74380|44.66421
S|(K51)|32.73391|44.67588
S|(K60)|32.61804|44.75496
S|(K65)|32.57736|44.73479
S|(K77)|32.57412|44.78964
S|(K81)|32.57608|44.80290
S|(K82)|32.55230|44.80326
S|(K83)|32.54566|44.79644
S|(K87)|32.50709|44.84569
S|(K88)|32.51316|44.85214
S|(K89)|32.52023|44.85624
S|(K111)|32.58209|44.85082
S|(K121)|32.62696|44.40666
S|(K129)|32.56943|44.45077
S|(K131)|32.55340|44.49392
S|(K132)|32.54691|44.49542
S|(K137)|32.54784|44.53797
S|(K138)|32.54899|44.55188
S|(K140)|32.50674|44.55629
S|(K146)|32.52933|44.61662
S|(K149)|32.52900|44.67466
S|(K150)|32.52733|44.67487
S|(K163)|32.52836|44.86121
S|(K168)|32.55813|44.80659
S|(K170)|32.56362|44.82246
S|(K171)|32.57927|44.86135
S|(Kabr el-Badawi / Khirbet el-Moulali)|36.71067|42.80804
S|(Kabr Umm et-Tuwaib)|32.07314|47.47039
S|(Kafr Falus)?|33.54343|35.47515
S|(Kahun)|29.23855|30.98495
S|(Kalecik)?|38.95402|38.79423
S|(Kaman Kalehöyük)|39.36273|33.78650
S|(Kamarian)|36.09191|44.94000
S|(Kamiltepe)|39.85570|47.38063
S|(Kangavar)|34.50164|47.96017
S|(Kani Shaie)|35.33285|45.10348
S|(Kani Shayah)|35.55795|45.17642
S|(Kapalıkaya)|39.58335|33.42837
S|(Kaplantu)?|36.23980|46.72477
S|(Karagündüz)|38.69596|43.64480
S|(Karahan Tepe?)|37.13750|39.50611
S|(Karahöyük Elbistan)|38.26111|37.11422
S|(Karahöyük Gedikli)|37.21999|36.83196
S|(Karahöyük Konya)|37.82052|32.44813
S|(Karahüyük)|37.03764|38.35962
S|(Karakeçi)|37.45254|39.43698
S|(Karatepe)|36.34618|36.35895
S|(Karatepe)|36.34945|42.42626
S|(Kara Tepe)|36.97813|40.95730
S|(Karhane)|34.49795|47.99744
S|(Karhol es-Sufla)|36.64546|42.87783
S|(Karunah K95)|32.67297|44.82436
S|(Katarlı)|37.15224|40.41942
S|(Kaula Kandal)|35.79842|43.62836
S|(Kavuşan Höyük)|37.82534|40.71691
S|(Kazane Höyuk)|37.11980|38.84575
S|(Kebeli / Babil / Kiri Mali)|37.18730|42.02758
S|(Kefadiz Hüyük)|37.19819|36.92725
S|(Kenan Tepe)|37.83057|40.81334
S|(Kepen)|39.38516|31.49254
S|(Kerkenes Dağ)|39.74827|35.06565
S|(Kerma)|19.60084|30.40993
S|(Kermezteppe)|35.03207|48.95015
S|(Khafaja C)|33.34927|44.55017
S|(Khafaja D)|33.34960|44.55578
S|(Khajrat Mulaikha)|30.88445|46.34617
S|(Khalet al-Jam'a)|31.68176|35.21063
S|(Khanijdal)|36.67738|42.26197
S|(Khanijdal east)|36.67964|42.28748
S|(Khan Shaykhun)|35.44329|36.64630
S|(Kharaba Bini Dahar)|34.08377|42.38033
S|(Kharab 'Arnan)|36.76582|39.95221
S|(Kharaba Tibn / Tell Abu Hajar)|36.73077|42.44883
S|(Kharab el-'Asheq)|36.76186|42.46056
S|(Kharab Sayyar)|36.58982|39.56621
S|(Kharaib Abu Ṣukhayr)|33.45442|43.81612
S|(Kharaib el-Qadisiya)|34.09459|43.95840
S|(Kharaib Hwaish)|36.15969|42.85561
S|(Kharaib Mahlabiyah)|36.27043|42.70048
S|(Khrabe Kngr S 060)|36.66648|43.66659
S|(Khariba Ahmar 'Ain)|32.33242|44.64470
S|(Khasak)|37.07929|40.84475
S|(Khazna Kabira)|36.99255|41.40098
S|(Khazneh)?|36.28434|42.44733
S|(Khiraib Sidria / Isdere)|35.44250|43.29696
S|(Khirbet 'Aloki)|36.69320|42.22272
S|(Khirbet Aziz)|35.29051|44.00749
S|(Khirbet Bel'ameh)|32.44551|35.29090
S|(Khirbet Chenchi)?|36.48729|43.23430
S|(Khirbet Dhiman SS 11)|36.26401|38.23983
S|(Khirbet ed-Daba'a)?|32.74363|37.27666
S|(Khirbet ed-Duwer)|32.68393|35.62872
S|(Khirbet el-'Abd)|36.79132|41.99360
S|(Khirbet el-'Ayyun)?|32.71866|35.66703
S|(Khirbet el-Balu')?|31.36572|35.78218
S|(Khirbet el-Batrawy)|32.08705|36.07111
S|(Khirbet el-Bizuna)?|36.07115|43.15574
S|(Khirbet el-Bustan)?|36.68006|42.72266
S|(Khirbet el-Ra'i)|31.59085|34.81943
S|(Khirbet el-Umbashi)|33.05440|36.97371
S|(Khirbet en-Naddas)|35.96907|42.93657
S|(Khirbet en-Nahas)|30.68091|35.43625
S|(Khirbet et-Tair)|36.05793|42.88006
S|(Khirbet ez-Zeraqon)|32.58638|35.94844
S|(Khirbet Hassan el-Yasin)|36.25445|42.97414
S|(Khirbet Hism Afnadi)|35.37554|43.87773
S|(Khirbet Iskander)|31.55672|35.77119
S|(Khirbet Islim)?|33.23147|35.42517
S|(Khirbet Jamu)|36.92345|41.23414
S|(Khirbet Jyea)?|36.15467|42.82500
S|(Khirbet Karhasan)|36.81056|42.52284
S|(Khirbet Khan el-Zanazil)?|36.44149|42.81126
S|(Khirbet Khatuniyeh)|36.62959|42.86669
S|(Khirbet Khebbar)|32.35198|35.27693
S|(Khirbet Kusiya)|32.42053|35.01506
S|(Khirbet Mazra'at Kanaf)|32.87127|35.68680
S|(Khirbet Muezer?)|36.25847|40.32485
S|(Khirbet Mughayyir)|33.34543|36.51580
S|(Khirbet Qara Quwiynili)?|36.22560|43.22650
S|(Khirbet Qaṣrij)|36.63363|42.90053
S|(Khirbet Qeiyafa)|31.69641|34.95751
S|(Khirbet Qumran)|31.74119|35.45894
S|(Khirbet Shiha)|36.72810|41.34747
S|(Khirbet Umm 'Adham)|36.23477|42.89865
S|(Khirbet Zakaria)?|36.28217|43.36322
S|(Khisham)|36.70528|40.56000
S|(Khosh Teppe)?|35.08039|44.41115
S|(Khraifat)|31.51837|44.97967
S|(Khubul)|36.58524|42.29162
S|(Kilik Mishik EPAS 4)|36.15771|43.97739
S|(Kilise Tepe)|36.50246|33.55364
S|(Kilo31)|32.89079|44.43296
S|(Kimash Sifla)|35.32679|45.81762
S|(Kınık Höyük)|37.93729|34.38008
S|(Kırmıtlı)|36.71433|38.78200
S|(Kırşehir)|39.14591|34.15803
S|(Kocatepe)|37.23689|40.16411
S|(Kol Teppe)|36.75450|38.65795
S|(Kom Abu Tahun)|31.20044|30.70610
S|(Kom Bashallis)|31.33926|31.35951
S|(Kom ed-Daba)|31.26462|30.91551
S|(Kom ed-Dahab)|31.31370|31.83232
S|(Kom el-Ahmar)|31.21227|31.04184
S|(Kom el-Arab / Kafri)|31.31649|30.72222
S|(Kom el-Fuqa)|31.36868|30.78348
S|(Kom el-Garad)|31.32839|30.90071
S|(Kom el-Ghuraf)|31.21479|30.41775
S|(Kom el-Giza)|31.13942|30.19291
S|(Kom el-Haddadi)|31.33289|30.78881
S|(Kom el-Khanziri)|31.35850|30.92971
S|(Kom el-Khariba)|31.32842|30.84873
S|(Kom el-Khawaled)|31.29023|30.86110
S|(Kom el-Khubbeiza)|31.38695|30.83195
S|(Kom el-Nuss el-Kebir)|31.16170|30.44879
S|(Kom el-Nuss el-Saghir)|31.17505|30.45640
S|(Kom esh-Sheikh Ismail)|31.24489|30.70267
S|(Kom Firin)|30.86444|30.48863
S|(Kom Ghitas)|31.22875|30.25887
S|(Kom Ibn Salam)|31.17923|32.08360
S|(Kom Manous)|30.41221|30.85215
S|(Kom Niqeiza)|31.46569|31.25766
S|(Kom Radwan)|30.92869|30.21368
S|(Kom Sheikh Ibrahim)|31.28072|30.75185
S|(Kom Talluz)|31.23640|30.31363
S|(Konar Sandal North/ Jiroft)|28.46354|57.77926
S|(Konar Sandal South / Jiroft)|28.44958|57.77878
S|(Könk)?|38.61152|39.43058
S|(Körtepe)?|38.64225|39.52542
S|(Körtik Tepe)|37.81424|40.98382
S|(Korucu Tepe)?|38.63698|39.53269
S|(Koruklu)|36.89623|38.92078
S|(KS 5)|32.15416|48.49078
S|(KS 6)|32.14443|48.50127
S|(KS 22)|32.26044|48.25655
S|(KS 32)|32.12249|48.29379
S|(KS 33)|32.13652|48.29661
S|(KS 34)|32.14776|48.29359
S|(KS 44)|32.16721|48.42611
S|(KS 52)|32.13979|48.27329
S|(KS 284)|32.11278|48.52892
S|(Kudish Saghir)|35.35295|44.26819
S|(Kulaçtepe)|38.20541|40.69750
S|(Kul-i Farah / Malamir)|31.87079|49.92907
S|(Kunara)|35.51930|45.35782
S|(Kuntillet 'Ajrud)?|30.19166|34.42499
S|(Kurban Höyük)|37.47597|38.42923
S|(Kurtbaba)|37.70325|32.77043
S|(Kuşçu)|37.29411|40.25956
S|(Kutha South 1)|32.73566|44.63875
S|(Kuwayrish)|33.13891|44.33072
S|(Laba'a)?|33.54705|35.45329
S|(Lawiya)?|32.84680|35.68009
S|(Lejma)?|33.64028|45.68962
S|(Lek Teppe)?|36.29845|43.26343
S|(Lidar Höyük)|37.56143|38.60612
S|(Liftaya)|34.65667|36.46220
S|(Lothal)|22.52262|72.24903
S|(Madain)|31.45659|45.51556
S|(Madain Salih)|26.78972|37.94929
S|(Mahirja)|36.92909|40.95066
S|(Makaraz Tepe)?|38.64818|39.44353
S|(Makhrut)|34.12322|44.08373
S|(Makhtjib)?|35.45998|43.58601
S|(Malah)|35.30709|36.52173
S|(Malhat ed-Deru)|35.93106|40.34756
S|(Malia)|35.29318|25.49274
S|(Malkata)|25.71618|32.59349
S|(Malmooze K34)|32.63246|44.49777
S|(Maltai)?|36.85757|42.94004
S|(Maltai relief)|36.84055|42.94503
S|(Maltepe)|36.47311|33.53171
S|(Maluan)|35.32110|45.73895
S|(Mamuca)|37.07713|39.02860
S|(Manjaz)?|34.61583|36.24554
S|(Masjed-e Suleiman)|31.98374|49.28161
S|(Masuh)|31.78334|35.83658
S|(Masur KR5)|33.43972|48.32182
S|(Manṣur)|36.74428|40.81961
S|(Marif Teppe)|35.35356|45.66232
S|(Marlik Teppe)?|36.86882|49.52428
S|(Mastoruh)|31.48739|30.68621
S|(Mastuma)|35.87781|36.63077
S|(Mavaran)|37.01382|45.48043
S|(Medar D492)|33.29492|44.74970
S|(Medinet el-Far)|36.53888|39.11422
S|(Merejib)|30.86598|46.18567
S|(Merimde Beni-Salama)|30.30114|30.84195
S|(Merj Abu Sharib)|36.14583|38.99646
S|(Merquly)|35.74415|45.23703
S|(Mesherfet el-Khanzir)|35.48123|36.94867
S|(Metsamor)|40.12636|44.18670
S|(Metuna)?|32.95084|36.60093
S|(Meydankapı)|36.78496|39.15784
S|(Mezraa Höyük)|36.97056|37.99768
S|(Mezraa Teleilat Höyük)|36.97732|37.98627
S|(Minet el-Beida)|35.60788|35.77598
S|(Minet el-Hosn)|33.89985|35.49735
S|(Mirabad Teppe I)|36.98657|45.30757
S|(Mishrifat SS16A)|36.29017|38.22022
S|(Misis)|36.95767|35.62380
S|(Misraab)|36.71593|37.64044
S|(Mlywi)|31.68448|45.16852
S|(Mohasan)|35.22221|40.30336
S|(Mohenjodaro)|27.32466|68.13619
S|(Molla Assaad)|36.61768|38.02971
S|(Mostabli)??|33.42038|36.24059
S|(Moumsiye)??|33.08228|35.83447
S|(Mourek)|35.37235|36.68948
S|(Mrekis)|36.88418|40.24866
S|(Mudir)|32.95612|44.61531
S|(Muhacirosman Köy)|36.91042|37.22664
S|(Muhayshich D660)|33.14625|45.34485
S|(Munbata)|35.76115|37.52991
S|(Mushatta)|31.73784|36.01023
S|(Mushiya)|36.71533|42.35114
S|(Müslümantepe)|37.80442|40.93629
S|(Naail)|32.73230|43.94557
S|(Nahib)|32.16444|44.45016
S|(Nahr el-Bared)|34.51131|35.96040
S|(Nahr el-Kalb)|33.95540|35.59672
S|(Najmuk)|36.47295|43.18875
S|(Nakhla)|32.06870|44.70179
S|(Naqada)|25.97091|32.73323
S|(Naqadeh)|36.95540|45.38800
S|(Naqsh-i Rustam)|29.98890|52.87446
S|(Nehirvan Höyük)|37.20799|42.41921
S|(Nemrik)|36.74018|42.82046
S|(Nemrut Dağı)|37.98068|38.74073
S|(Niliyah K162)|32.50121|44.86388
S|(Norşun Tepe)?|38.62557|39.47200
S|(Nustell)|36.66062|40.61595
S|(Ören Qale)|39.83582|47.50343
S|(Ortaköy)|37.22528|40.78427
S|(Oura)|35.54137|36.67971
S|(Oymaağaç Höyük)|41.20761|35.42937
S|(Ozbaki)|35.97953|50.58658
S|(Paikuli)|35.10076|45.58309
S|(Palaikastro)|35.19544|26.27557
S|(Parapara)|36.94955|38.94544
S|(Paşa Höyük)|36.34528|36.49038
S|(Qabb Elyas)?|33.79546|35.82013
S|(Qabr 'Ali)|36.95390|40.80969
S|(Qabr Ḥajir)|36.16004|41.70862
S|(Qabr Maqluba)|33.61290|42.79643
S|(Qabr Mella Jasim)|36.36917|42.38779
S|(Qabr Un?)|32.89664|44.78431
S|(Qabur Fadhil)|33.21715|43.98108
S|(Qabur Fadhil)|33.21012|43.97402
S|(Qadariya)|36.12194|43.66379
S|(Qa'la Bast)|31.50809|64.35680
S|(Qala Khandan Teppe)|36.82561|54.41916
S|(Qala Shirwana SRP 1)|34.60689|45.31339
S|(Qalaichi)|36.57028|46.27521
S|(Qal'at Ali el-Umaish)|31.78502|44.57137
S|(Qal'at Dizah)|36.18534|45.11483
S|(Qal'at el-Bahrain)|26.23292|50.52153
S|(Qal'at el-Marqab)|35.15215|35.94960
S|(Qala Tepe)|40.00144|47.35266
S|(Qal'at er-Raḥiyya)|35.27923|37.10830
S|(Qal'at er-Rouss)?|35.41761|35.91701
S|(Qal'at esh-Shmemis)|35.03671|37.01353
S|(Qal'at Hajji Muhammed)?|31.21801|45.56143
S|(Qal'at-i Dinka)|36.13689|45.13264
S|(Qal'at Najm)?|36.55467|38.26129
S|(Qal'at Nimrod)|33.25265|35.71498
S|(Qal'at Qurshaqlu)|35.92368|43.92711
S|(Qal'at Rashit er-Rayt)|32.98611|44.49981
S|(Qa'at Said Ahmadan)|36.22509|45.14688
S|(Qal'at Saratak)|35.83052|44.30655
S|(Qal'at Surbash)|35.91718|43.96062
S|(Qalatga Darband)|36.21293|44.97734
S|(Qalbaza Teppe)?|35.26697|45.81089
S|(Qal'e-ye Toll)?|31.63213|49.88978
S|(Qana)?|33.20928|35.29966
S|(Qaradere)|36.62149|42.89689
S|(Qaqun)|32.35959|34.99510
S|(Qara Keupru)|36.63588|37.26180
S|(Qara Mazra')|36.65225|37.28106
S|(Qara Quzak)|36.63274|38.21475
S|(Qarashina)|36.12287|44.93064
S|(Qarateppe)|37.48759|45.23151
S|(Qasr Bshir)|31.33731|35.98119
S|(Qasr-e Abu Nasr)|29.58466|52.62524
S|(Qasr ed-Dib)|37.22939|42.14007
S|(Qasr el-Hayr esh-Sharqi)|35.07408|39.07113
S|(Qasr Ibrim)|22.64954|31.99274
S|(Qaṣrij Cliff)|36.63465|42.89757
S|(Qastoun)|35.68592|36.38764
S|(Qatranya / Bur Sa'id)|37.03147|41.64514
S|(Qattine)|37.02032|40.69704
S|(Qisrin)|32.98868|35.70507
S|(Qiz Qal'eh)|37.77803|45.06084
S|(Qleidine)|35.61272|36.38514
S|(Qreiye-'Ayyash)|35.42689|40.05952
S|(Qubba)|36.67416|38.15608
S|(Qubr Banat el-Husn)|32.23664|44.43182
S|(Qubur el-Walaydah)|31.33373|34.48506
S|(Qaburstan)|35.98808|43.89618
S|(Raba'a K43)|32.56898|44.63410
S|(Rabat Teppe)|36.21276|45.55519
S|(Rajajil)|29.81269|40.21955
S|(Rakhigarhi)|29.28931|76.11269
S|(Ramat Rachel)|31.73974|35.21695
S|(Ramahiyah)|31.89863|44.70696
S|(Ramat Razim)?|32.96535|35.51715
S|(Ramalah SS 16B)|36.29634|38.22022
S|(Ras el-'Amiya K40)|32.60026|44.65372
S|(Ras el-Bassit)|35.84991|35.82466
S|(Ras Ibn Hani)|35.58748|35.73603
S|(Rasm Buldagh)|35.20041|44.19547
S|(Redau Gharbi)|31.32624|45.55219
S|(Redau Sharqi)|31.32057|45.55328
S|(Rejibah Jinub)|30.89930|45.97100
S|(Rejibah Shamal)|30.90404|45.96810
S|(Rejim Hassan)|36.71641|42.07648
S|(Rejim Sarrak)|36.45846|40.85688
S|(Rejim Sleibi)|36.58410|41.13195
S|(Resan)|37.14059|42.33790
S|(Rosetta)|31.39895|30.41696
S|(Rujm el-Hiri)|32.90862|35.80106
S|(Rujm Fiq)|32.79439|35.72509
S|(Sabuniye)|36.08151|36.00297
S|(Şadı Tepe)|36.89820|38.01534
S|(Ṣafi)|32.34353|44.43259
S|(Safira)?|36.07771|37.37132
S|(Sagzabad)?|35.84240|49.95278
S|(Saibakh)|36.66204|41.09897
S|(Sakavand /Eshaqvand / Deh-e Now)?|34.22847|47.42645
S|(Salat Cami Yanı)|37.84072|40.89424
S|(Salat Tepe)|37.83944|40.90171
S|(Salba)|35.33511|36.44635
S|(Sandi)|36.58199|37.57200
S|(Şaraga Höyük)|36.91936|38.00098
S|(Sar-e Pol-e Zahab)|34.46255|45.86939
S|(Sarıt Mezrea)|36.90291|37.25942
S|(Saruj)?|36.03707|43.20206
S|(Şavi Höyük)|36.94154|38.01027
S|(Sazgın)|36.94117|37.46175
S|(Seh Qubba)|36.85844|42.49093
S|(Seksenören)|36.97423|39.07453
S|(Sepphoris)|32.75347|35.27912
S|(Serabit el-Khadim)|29.03680|33.45930
S|(Sergilla)|35.67067|36.56942
S|(Se Teppe)|35.25320|44.60030
S|(Sewandik Teppe)|35.00820|44.17809
S|(Seylan)|36.94313|37.50601
S|(Shaaara)|33.10737|36.34882
S|(Shab'a)?|33.45075|36.39014
S|(Shahdad)?|30.42740|57.74447
S|(Shahr-i Sokhte)|30.58933|61.32241
S|(Shah Savar / Malamir)|31.81641|49.95369
S|(Shah Teppe)|36.93984|54.35143
S|(Shajara Saghira SS 29)|36.28743|38.18879
S|(Shakhsi Teppe)|36.93835|45.50845
S|(Shambara)|32.13562|44.68166
S|(Shams ed-Din central tell T 536)|36.24878|38.17427
S|(Shamsin)?|34.54043|36.74084
S|(Shanidar Cave)|36.83120|44.22024
S|(Sheikh Barana)|35.55869|36.97341
S|(Sheikh Hadr)|32.85056|35.64953
S|(Sheikh Mansour)|35.86555|36.86463
S|(Sheikh Zennad)|34.60287|35.98915
S|(Shibaniyat Dahham)|36.96441|41.35723
S|(Shishin)?|33.96301|42.57591
S|(Shjarah)|35.22285|43.41903
S|(Shraim K35)|32.62452|44.50461
S|(Si')|32.73502|36.62744
S|(Sidakan)|36.80494|44.61771
S|(Siha Sahwah)|36.74961|40.87103
S|(Sirkeli Höyük)|37.00309|35.74341
S|(Siverek)|37.75519|39.31667
S|(Soğuksu Hüyük)|36.46416|36.31819
S|(Söǧütlü)|37.12345|41.56753
S|(Songrus Hüyük)|37.21325|36.89604
S|(Sos Höyük / Yiğittaşi)|39.99335|41.52325
S|(Sotk)|40.19804|45.86654
S|(Soultane)|35.80700|36.97469
S|(Sqalbiye)|35.36795|36.39361
S|(SRP 9)|34.65261|45.38840
S|(SRP 42)|34.51607|45.26415
S|(SRP 46)|34.51655|45.26883
S|(SRP 93)|34.52160|45.27121
S|(SRP 94)|34.51783|45.27401
S|(SRP 121)|34.52311|45.27373
S|(SS 24)|36.24914|38.20360
S|(Subkhayet el-Bezel / Abu Dihin K126)|32.60956|44.40271
S|(Sughana Fawqani)|36.98559|40.86229
S|(Sughana Tahtani)|36.96847|40.86133
S|(Sultan 'Abdullah)|35.89601|43.39074
S|(Suq esh-Shuykh)|30.89124|46.47360
S|(Suq Lemlum)|31.65185|45.06615
S|(Surman)|35.61279|36.84682
S|(Takht-i Rustam)|29.96675|52.88259
S|(Takht-i Suleiman)|36.60462|47.23482
S|(Takyan Höyük)|37.17945|42.39525
S|(Talib)|31.96660|44.74454
S|(Tanburit)?|33.51531|35.41612
S|(Taq-e Bostan)|34.38737|47.13218
S|(Taşlıbakar)?|36.70366|37.40377
S|(Taşlı Geçit Höyük 2)|36.93316|36.70607
S|(Taşlı Geçit Höyük 1)|36.92641|36.71077
S|(Taşlik Höyük)|39.80162|35.02698
S|(Tas-Silġ)|35.84576|14.55182
S|(Tawilan)|30.33148|35.48482
S|(Tchatal)|37.04242|40.84761
S|(Tel Afeq)|32.84558|35.11141
S|(Tel 'Agol)|32.63134|35.37203
S|(Tel Anafa / Tell el-Akhdar)|33.17704|35.64471
S|(Tel Avel Bet Ma'aka)|33.25925|35.58034
S|(Tel Bet Yerah / Khirbet el-Kerak)|32.71528|35.57179
S|(Tel Birah)|32.90137|35.16920
S|(Tel Burna)|31.62966|34.87349
S|(Tel Dotan)|32.41280|35.23866
S|(Teleillat Ghassul)|31.80599|35.60420
S|(Tel 'Erani / Tell el-'Areini)|31.61152|34.78524
S|(Tel Esur / Tell el-Asawir)|32.48210|35.01924
S|(Tel 'Eton)|31.49021|34.92838
S|(Tel Gerisah)|32.09157|34.80768
S|(Tel Gev'a Shemen)|32.72829|35.09668
S|(Tel Hadid)|31.96358|34.95187
S|(Tel Haror / Tell Abu Hureireh)|31.38176|34.60698
S|(Tel Ḥalif / Tell Khuweilifeh)|31.38256|34.86676
S|(Tel Hebron / Tell Rumeida)|31.52515|35.10204
S|(Tel 'Ira / Khirbet Ghara)|31.23310|34.98583
S|(Tel Kabri)|33.00837|35.13922
S|(Tel Kinnerot / Tell el-'Oreimeh)|32.86932|35.53972
S|(Tel Kitan)|32.59010|35.57359
S|(Tell Ababra)|34.21729|44.99309
S|(Tell Abada)?|34.10965|45.12281
S|(Tell 'Abbar)|32.43158|44.43173
S|(Tell Abbas)|32.55507|44.95606
S|(Tell 'Abdal)|36.27404|36.53787
S|(Tell Abid)|36.68424|38.98545
S|(Tell Abla)|31.33248|45.94368
S|(Tell 'Abra)|37.02909|41.78843
S|(Tell Abraq)|25.48780|55.55204
S|(Tell 'Abriya Gharbi)|35.88747|42.84370
S|(Tell Abtah)|36.21351|42.16205
S|(Tell Abtah)|36.70907|42.02892
S|(Tell Abtah)|36.51965|42.08507
S|(Tell Abtakh Faouqani)|36.81554|41.53168
S|(Tell Abu Ajrash / Ishan Abu Haṭab K39)|32.63655|44.66545
S|(Tell Abu Ali)|34.74968|35.97833
S|(Tell Abu Antik)|32.19971|44.47200
S|(Tell Abu Antik / Bikasi 1)|32.13144|44.63882
S|(Tell Abu 'Aras)|32.66571|44.38841
S|(Tell Abu 'Arzal)|32.40321|44.38724
S|(Tell Abu 'Azawi)|32.86693|44.33235
S|(Tell Abu Bakr)|36.49586|40.77299
S|(Tell Abu Bureij)|32.69298|44.71245
S|(Tell Abu Dam)|32.87557|44.31659
S|(Tell Abu Danne)|36.17889|37.45161
S|(Tell Abu Dar'a)|32.82766|44.38694
S|(Tell Abu Dhaba A052)|33.17624|44.20688
S|(Tell Abu Dhaba')?|32.30966|45.51227
S|(Tell Abu Dhaba' H1293)|32.03859|45.62568
S|(Tell Abu Dhaba')?|32.82041|44.96694
S|(Tell Abu Daba')|32.28160|45.52040
S|(Tell Abu Dhahir)|36.83703|42.49350
S|(Tell Abu Dhibah K31)|32.69221|44.51006
S|(Tell Abu Dhuwil)|36.94559|41.19669
S|(Tell Abu Dibis D842)|32.89885|45.30671
S|(Tell Abu Drikha)|35.58941|37.16586
S|(Tell Abu Duwari H848)|32.22998|45.30201
S|(Tell Abu el-Alej)|35.52244|37.11766
S|(Tell Abu el-Kharaz)|32.39901|35.59444
S|(Tell Abu eṣ-Ṣuṣ)|32.37367|35.56104
S|(Tell Abu ez-Za'ar)|32.50334|44.44894
S|(Tell Abu Fahd)|35.61628|39.87284
S|(Tell Abu Far'a)|36.89244|41.62438
S|(Tell Abu Ghafil)|32.94384|44.62614
S|(Tell Abu Gharaq)|32.79217|44.24547
S|(Tell Abu Hafayir)|33.07463|44.31789
S|(Tell Abu Hafur)|36.60714|40.66120
S|(Tell Abu Hajjar)|36.90865|41.95743
S|(Tell Abu Hajar)|36.53744|40.74569
S|(Tell Abu Hajira / Tell 'Uqla Tahtani)|36.76727|42.20929
S|(Tell Abu Hawam)|32.80158|35.01987
S|(Tell Abu Hujeira I)|36.62679|40.64291
S|(Tell Abu Hurayba)|32.89340|44.57170
S|(Tell Abu Huraybah A151)|32.76625|44.70677
S|(Tell Abu Hurayrah)|35.86911|38.38532
S|(Tell Abu Husaini)|34.27269|45.00815
S|(Tell Abu Ja'ari D252)|33.45521|44.76564
S|(Tell Abu Jaraba)|36.52903|41.13236
S|(Tell Abu Jarathi)|36.11694|42.93504
S|(Tell Abu Jelamid A013)|33.83832|44.32103
S|(Tell Abu Jiniya)|31.90250|44.79873
S|(Tell Abu Kabur)|31.60291|46.16887
S|(Tell Abu Kald)?|32.88610|44.67033
S|(Tell Abu Kassab)|36.63053|41.27640
S|(Tell Abu Kelb H884)|32.40731|45.73476
S|(Tell Abu Khamis)|32.45287|44.79329
S|(Tell Abu Khanzir)??|33.06891|35.77054
S|(Tell Abu Khay H901)|32.26702|45.64734
S|(Tell Abu Khazaf)|36.87060|41.42612
S|(Tell Abu Laban)|32.94523|44.55601
S|(Tell Abu Najur)|36.78959|41.17679
S|(Tell Abu Nida)|33.11037|35.78978
S|(Tell Abu Qabis)?|34.88425|36.91555
S|(Tell Abu Qadeir)|36.85377|41.66589
S|(Tell Abu Qasim)?|36.07558|41.57791
S|(Tell Abu Qasim)|34.30652|44.99385
S|(Tell Abu Qaws)|32.62027|44.33853
S|(Tell Abu Qbara)|36.82385|41.61712
S|(Tell Abu Rahim el-Sharqi)|32.92428|44.51420
S|(Tell Abu Ras'ain)|30.83464|46.22811
S|(Tell Abu Rasayn)|36.85250|40.32691
S|(Tell Abu Rasayn)|33.65338|45.16721
S|(Tell Abu Rusiyat? H542)|32.55974|45.18942
S|(Tell Abu Salabikh E28)?|30.84791|46.20529
S|(Tell Abu Sha'ib)?|30.75454|47.13310
S|(Tell Abu Shajir)|32.49511|44.16717
S|(Tell Abu Shakhama)?|35.14108|44.12659
S|(Tell Abu Shakhat)|36.64506|39.74258
S|(Tell Abu Sakhra)|32.56419|44.43536
S|(Tell Abu Satai)|32.86669|44.43530
S|(Tell Abu Shejar H878)|32.33693|45.54031
S|(Tell Abu Shijar)|33.35416|44.18929
S|(Tell Abu Simsim)|32.57807|45.01750
S|(Tell Abu Siye)??|33.39915|36.10677
S|(Tell Abu Ṣukhir / Abu Sukhiya A056)|33.21801|44.40702
S|(Tell Abu Tahun)|31.03785|31.76982
S|(Tell Abu Ṭaqiya)|36.15369|41.48119
S|(Tell Abu Taruf)|32.56911|44.33218
S|(Tell Abu Tubunjah)|32.51829|44.48448
S|(Tell Abu Wadiya H1321)|31.95644|45.09564
S|(Tell Abu Winni)|36.62871|42.46697
S|(Tell Abu Zambil D384)|33.37053|45.03941
S|(Tell Abu Zaytun)|32.83148|35.80077
S|(Tell Abu Zorf el-Abyadh H625)|32.48746|45.51452
S|(Tell Abu Zorf el-Aswad H626)|32.49123|45.54148
S|(Tell Abu Zoueil)|36.95866|41.19200
S|(Tell Abu Zumal)|31.48812|45.83652
S|(Tell Abyad)|32.94599|45.98951
S|(Tell Abyad)|33.35884|44.19197
S|(Tell 'Adas)|37.01093|42.08293
S|(Tell Adna)?|35.13479|43.47220
S|(Tell Adris Sharqi)|36.78027|41.29519
S|(Tell 'Afar)|36.37435|42.45413
S|(Tell Afyun)|35.05251|36.66692
S|(Tell Agrab D515)|33.33909|44.87463
S|(Tell Ahal)|33.40296|36.41159
S|(Tell Ahmad)|34.61329|36.68505
S|(Tell Ahmad)|36.85249|41.35089
S|(Tell Ahmar)|33.37285|44.16724
S|(Tell Ahmar)|36.96130|41.06439
S|(Tell Ahmar)|36.63282|37.41311
S|(Tell Ahmed el-Mughir)|34.35056|44.98015
S|(Tell 'Aid)|36.94743|41.33625
S|(Tell ʿAin Dara)|36.45980|36.85291
S|(Tell 'Ain el-Beida)|36.72600|37.97095
S|(Tell 'Ain Shrida)|36.03747|42.92013
S|(Tell 'Aisha)|31.85489|44.51360
S|(Tell Aiyab?)??|33.18616|35.95829
S|(Tell Ajamat)|34.35963|44.98091
S|(Tell 'Ajar)|36.49363|37.03375
S|(Tell 'Ajol)|35.21853|44.24368
S|(Tell 'Akasha)??|33.03087|35.86337
S|(Tell Akhmar? esh-Sharqi)??|32.99157|35.90082
S|(Tell Akhmar? el-Gharbi)??|32.99657|35.88232
S|(Tell Akhsi)|36.68473|38.84506
S|(Tell Akrah)|35.50262|43.42078
S|(Tell Akrah)|32.23954|45.74701
S|(Tell Akram)|34.34914|44.97509
S|(Tell 'Alaqiye)??|33.14498|36.08043
S|(Tell al-Faras)|35.20116|43.40187
S|(Tell 'Ali Agha)|36.90335|41.89849
S|(Tell 'Alibat)|35.66988|42.86712
S|(Tell 'Alo)|36.93841|41.78657
S|(Tell Alwan)|35.28885|44.15918
S|(Tell Alwe)|32.42662|44.54334
S|(Tell Alwiya)|32.85690|44.53798
S|(Tell 'Amarin)|36.93434|41.37483
S|(Tell Amarna)|36.74532|38.01371
S|(Tell Amkip)|35.58034|36.38584
S|(Tell 'Amqiye west)|35.58698|36.35635
S|(Tell 'Amra H627)|32.52673|45.56265
S|(Tell 'Amuda)|37.13288|40.93342
S|(Tell 'Anab as-Safinah)|36.23251|38.13834
S|(Tell Anbar)|33.37903|43.71713
S|(Tell 'Anntar)??|33.13661|36.08754
S|(Tell Antar / Tell Mas'ud Kabir)|36.83934|42.03098
S|(Tell Antika K13)|32.54126|44.59936
S|(Tell 'Aqab)|37.05802|40.89573
S|(Tell Aqram)?|30.77576|46.83318
S|(Tell 'Ar)?|36.57432|37.40367
S|(Tell 'Arab Hassane)|36.65266|37.85423
S|(Tell 'Arade)|37.00391|40.40225
S|(Tell 'Arade)|36.79209|40.24060
S|(Tell 'Aran)|36.12420|37.34718
S|(Tell Aray)|35.91739|36.51648
S|(Tell 'Arbadiye)|35.99805|36.55510
S|(Tell 'Arbid)|36.87296|41.02183
S|(Tell 'Arbid Abyad)|36.87250|41.03205
S|(Tell 'Arbit)|35.42505|45.57967
S|(Tell Archaq)|36.51812|37.27026
S|(Tell Ardid?)|34.97280|37.02533
S|(Tell Arfa)|35.38118|37.01968
S|(Tell 'Arid)??|33.19708|36.14753
S|(Tell Arpachiyah / Tepe Reshwa)|36.37765|43.21093
S|(Tell 'Arquba)|36.65700|39.28357
S|(Tell Arquni)|34.58148|36.65652
S|(Tell 'Arus)|36.92336|40.89975
S|(Tell Arzah)?|35.17552|36.70181
S|(Tell As)|35.43179|36.58954
S|(Tell Ašamsani)?|35.87790|40.87166
S|(Tell 'Asayat)|33.01254|44.44175
S|(Tell Asga)|36.24955|42.19049
S|(Tell Ash'ari)|32.74349|36.01439
S|(Tell Ashnane Sharqi)|36.67615|40.39345
S|(Tell Ashta)|35.08087|44.19415
S|(Tell Aslawi)|36.71106|40.89989
S|(Tell Asnan)|36.73137|40.12816
S|(Tell Aswad)|33.22814|44.31565
S|(Tell Aswad)|33.40404|36.55007
S|(Tell Aswad)?|35.88769|43.08167
S|(Tell Aswad)|35.41790|43.57180
S|(Tell Aswad Fawqani)|36.67695|40.71777
S|(Tell Aswad Tahtani)|36.64387|40.72679
S|(Tell 'Atchash)|36.68887|40.19772
S|(Tell Atiwat el-Gharbi)|32.91315|44.43346
S|(Tell Atiwat el-Sharji)|32.92329|44.42298
S|(Tell Atshana)|37.00343|41.70963
S|(Tell 'Atij)|36.43058|40.86441
S|(Tell Atiqeh)|34.34233|44.97792
S|(Tell Awar)|35.73657|36.38482
S|(Tell Awarid)|36.95239|42.05929
S|(Tell Awarid Fawqani)|36.98367|42.11105
S|(Tell 'Aydo)|36.69391|41.78646
S|(Tell 'Aylun)|37.07975|40.66875
S|(Tell 'Ayn el-'Alaq)|36.52384|42.60648
S|(Tell Ayu / Bṣirin)|35.02509|36.73537
S|(Tell Ayyub)|36.61101|40.91243
S|(Tell 'Azana)|36.71431|41.08314
S|(Tell Azar)|33.21392|44.01439
S|(Tell Bab Omar)|34.70187|36.67933
S|(Tell Babul)?|36.39685|43.17248
S|(Tell Badan)?|37.06327|41.22453
S|(Tell Baherir Kabir)|36.77634|40.27786
S|(Tell Baherir Saghir)|36.81152|40.26953
S|(Tell Bahouerte)|36.57833|37.31300
S|(Tell Baluta / Tell Jiji)|36.34599|36.65972
S|(Tell Bahri esh-Shamal)|36.64110|42.17002
S|(Tell Bana)|31.00536|31.42078
S|(Tell Banat)|36.43693|38.28239
S|(Tell Bandar K8)|32.54380|44.60693
S|(Tell Bandar Khan)|36.70987|38.69924
S|(Tell Baraoum)??|33.15835|35.77854
S|(Tell Banduriya)|36.70108|41.26914
S|(Tell Baqar)|36.99871|40.73844
S|(Tell Baqrta EPAS 17)|35.95196|43.90993
S|(Tell Barabra)|36.55882|38.91728
S|(Tell Bararhite)|36.63441|37.20466
S|(Tell Baraz eṣ-Ṣaghir)|32.55775|44.11322
S|(Tell Barda)|36.75805|41.23733
S|(Tell Barda)??|33.21012|35.78891
S|(Tell Barish)|36.99654|41.34246
S|(Tell Barka)|36.72624|40.12297
S|(Tell Barr Elyas)|33.77553|35.90354
S|(Tell Barsuna)?|35.62974|35.78395
S|(Tell Bartala)?|32.90216|45.91664
S|(Tell Barzasha)|32.23692|45.55828
S|(Tell Bas)|36.97589|40.72563
S|(Tell Basha)|34.83827|36.79917
S|(Tell Bashbita)|36.33761|43.35910
S|(Tell Basmusiyan)|36.16157|44.92429
S|(Tell Bat el-Kom)|30.91394|30.16184
S|(Tell Bati)|36.72865|40.73417
S|(Tell Bat Karja?)|33.09215|35.83681
S|(Tell Batnan)|36.39534|37.53916
S|(Tell Battal Chimali)|36.64602|37.34606
S|(Tell Battil Sharqi)|36.50217|37.43431
S|(Tell Bawgha)|36.70070|39.87035
S|(Tell Bayandur)|37.02970|41.44019
S|(Tell Bazari)|36.60082|40.78665
S|(Tell Bazzam)|35.33583|36.74923
S|(Tell Begum)|35.29798|45.88409
S|(Tell Beibokh)|36.44918|43.19901
S|(Tell Beit Mersim)|31.45559|34.91064
S|(Tell Benja)|36.59492|41.40458
S|(Tell Berne)|36.03330|37.00692
S|(Tell Beshmaroun)|35.95941|36.54023
S|(Tell Bessiz)|36.88988|40.35020
S|(Tell Bibe)|34.61808|36.00652
S|(Tell Bindura)|36.70976|41.30039
S|(Tell Bint al-Saeigh)|30.73842|46.68974
S|(Tell Biri)|34.62756|36.05027
S|(Tell Bisha)?|32.14051|47.14600
S|(Tell Bismaya H882)|32.40916|45.64975
S|(Tell Bisseh)|34.84497|36.73041
S|(Tell Biss Kabir)|36.78462|41.24484
S|(Tell Biss Saghir)|36.77701|41.25674
S|(Tell Blaij)|36.92595|41.43896
S|(Tell Bom)|36.98268|40.55556
S|(Tell Borakhan D286)|33.52101|45.17310
S|(Tell Bourqala)??|33.28275|36.07776
S|(Tell Braidij)|35.38783|36.46340
S|(Tell Brak Castellum)|36.67179|41.06822
S|(Tell Bseisé)?|34.66547|36.03356
S|(Tell Buqras)|35.08699|40.39440
S|(Tell Buthat el-Rug'ai)|35.79462|42.94777
S|(Tell Bwed)|36.38775|40.80613
S|(Tell Chair)|36.61634|37.34325
S|(Tell Chanafes)|36.88060|40.17454
S|(Tell Chermoukh)|36.88685|41.38491
S|(Tell Chiṭṭel)|36.41936|43.25256
S|(Tell Chokha)|33.34268|43.69149
S|(Tell Dabal)|33.82464|45.13798
S|(Tell Dabesh)|36.93629|40.45879
S|(Tell Dadat)|36.63600|37.93128
S|(Tell Dades)|35.20920|36.41346
S|(Tell Dadin)|35.94382|37.08520
S|(Tell Dadja)|36.71707|41.83408
S|(Tell Dafa'a)?|35.18087|36.72696
S|(Tell Dakhab)?|35.56292|43.58644
S|(Tell Dakhral)|36.63618|41.88430
S|(Tell Dalhamiya)|33.81824|35.95900
S|(Tall Damiya)|32.10376|35.54682
S|(Tell Damm)|35.57451|36.89727
S|(Tell Daoud)|35.85761|36.47872
S|(Tell Daruk)?|35.27015|35.94632
S|(Tell Darwish)|33.15586|44.32446
S|(Tell Davutpaşa)|36.31808|36.60982
S|(Tell Dawish)|36.12972|41.65824
S|(Tell Dayr Zanun I)|33.75220|35.91846
S|(Tell Debbeh)|32.82620|36.57373
S|(Tell Dehala)?|36.04227|43.04642
S|(Tell Thahab / Deheb D667)|33.07699|44.58593
S|(Tell Dehlis)|36.57245|39.44393
S|(Tell Deir 'Alla)|32.19636|35.62079
S|(Tell Derdara)|36.83538|40.17251
S|(Tell Derek)?|36.49103|43.21037
S|(Tell Dhahab)|36.85860|41.18531
S|(Tell Dhahab)|36.89777|41.17678
S|(Tell Dhebian)??|33.08347|36.14221
S|(Tell Dhuwayj)?|36.78345|42.60954
S|(Tell Dibak)|36.88869|40.61128
S|(Tell Dibé)|36.66499|40.92926
S|(Tell Dibgu)|31.00913|31.97919
S|(Tell Dimou)|35.20114|36.44652
S|(Tell Dlehim H1237)|31.99783|45.41090
S|(Tell Dnaybi)|34.92733|37.00532
S|(Tell Dnine)|35.21078|36.92549
S|(Tell Duma)|35.34435|37.01344
S|(Tell Dumdum)|36.60274|41.31267
S|(Tell Duraj)|36.08593|42.59256
S|(Tell Duris I)|33.98499|36.18125
S|(Tell Dwanza Imam)?|35.25448|45.92277
S|(Tell-e Bakun A)|29.91368|52.88560
S|(Tell-e Bakun B)|29.91308|52.88833
S|(Tell Eddah)|34.79665|36.79186
S|(Tell ed-Daba)|31.25130|30.86094
S|(Tell eḍ-Ḍabi')?|32.21901|46.77508
S|(Tell ed-Dakhab?)|33.05440|35.85732
S|(Tell ed-Damdua)|31.28622|31.79154
S|(Tell ed-Dar)|33.69198|35.79482
S|(Tell ed-Daym)|36.12509|42.78567
S|(Tell ed-Daym K61)|32.65025|44.76797
S|(Tell ed-Dayr / El-Karimiya)|32.31514|44.98311
S|(Tell ed-Dîb)|35.25236|36.97607
S|(Tell ed-Drazi D675)|33.10781|44.77063
S|(Tell ed-Dukheimal / Ishan Duheimi)|31.84902|46.31232
S|(Tell edh-Dhahab)|33.03431|44.47670
S|(Tell edh-Dhaim / Yasah)|36.61689|42.27496
S|(Tell edh-Dhiba'i / Medina U064)|31.65839|45.51845
S|(Tell edh-Dhiba'i U055)|31.69193|45.52152
S|(Tell edh-Dhuba'i / Tell Najira H897)|32.38298|45.73012
S|(Tell-e Diban 1)|31.81957|48.87812
S|(Tell Effendi)|36.77663|40.69927
S|(Tell Egdimi)|35.93415|42.88427
S|(Tell-e Hasan)|31.94842|48.88276
S|(Tell-e Kalat)|31.96209|48.84868
S|(Tell-e Khandak)?|30.71748|50.16117
S|(Tell el-'Abd)|36.23457|38.13958
S|(Tell el-'Abir)|36.68145|38.08699
S|(Tell el-Abqaein)|30.88343|30.32820
S|(Tell el-Agharr)|35.76559|36.92115
S|(Tell el-Agharr)|35.22289|37.21901
S|(Tell el-Ahyamar)|32.80010|44.25639
S|(Tell el-'Ajjul)|31.46784|34.40408
S|(Tell el-Akhmar)??|33.21290|35.88130
S|(Tell el-Ammuriya)??|33.21804|35.77551
S|(Tell el-'Aoueïr)|35.16145|36.91451
S|(Tell el-'Aram)??|33.12917|35.78298
S|(Tell el-'Arar)??|32.68259|36.13824
S|(Tell el-Arba'in)|32.51909|35.59083
S|(Tell el-ArshanH 826)|32.30585|45.33868
S|(Tell el-Aruna)|35.23936|36.83015
S|(Tell el-Aswad)|36.58434|40.89692
S|(Tell el-Aswad)|32.81607|44.22816
S|(Tell el-Aswad)??|33.38431|36.31948
S|(Tell el-'Awishaj)?|31.75548|44.62137
S|(Tell el-'Azawayah)|32.79180|44.41605
S|(Tell el-Bahr / Tell et-Tin)|34.62043|36.53358
S|(Tell el-Bair)|36.20483|42.49701
S|(Tell el-Balan)|34.75586|36.85403
S|(Tell el-Barrak)|32.78637|44.93413
S|(Tell el-Bawiya)?|31.54642|45.37657
S|(Tell el-Bubier)?|36.10700|43.12168
S|(Tell el-Bughala)|36.41836|42.84775
S|(Tell el-Burak)|33.48211|35.32245
S|(Tell el-Butha)?|36.72593|42.25741
S|(Tell el-Buwayta)|36.12675|42.51985
S|(Tell el-Egrainy K122)|32.62432|44.40806
S|(Tell el-Fakhra)|35.07398|44.24379
S|(Tell el-Far)|35.31394|36.35020
S|(Tell el-Far'ah north)|32.28705|35.33963
S|(Tell el-Far'ah south)|31.28192|34.48252
S|(Tell el-Farass)??|32.95998|35.86458
S|(Tell el-Farkha)|30.87491|31.60157
S|(Tell el-Fas)|35.35753|36.62924
S|(Tell el-Fitil)|31.58561|46.18850
S|(Tell el-Fukhkhar)|32.58894|35.95310
S|(Tell el-Gane)|36.67776|37.72191
S|(Tell el-Ghara)|36.48375|40.29404
S|(Tell el-Ghashim)??|33.13127|36.13975
S|(Tell el-Gir)|31.22409|30.77497
S|(Tell el-Habbis el-Gharbi A095)|32.92608|44.58000
S|(Tell el-Habbis esh-Sharqi A096)|32.92960|44.58591
S|(Tell el-Halfayah D169)|33.59425|44.52436
S|(Tell el-Hammah)|32.37327|35.50039
S|(Tell el-Hammam)|31.83956|35.67319
S|(Tell el-Hammam)|34.16538|36.83129
S|(Tell el-Hargawi A055)|33.06085|44.20233
S|(Tell el-Harim)|36.08079|43.05051
S|(Tell el-Harra)|33.06199|35.99197
S|(Tell el-Hasinaba?)|32.90050|44.19189
S|(Tell el-Hawa?)??|33.26337|36.06425
S|(Tell el-Hawa)|36.74787|42.30128
S|(Tell el-Hayyad H1306)|32.04702|45.70134
S|(Tell el-Hesi)|31.54777|34.73030
S|(Tell el-Hudeira)|31.07616|46.73130
S|(Tell el-Husn)|32.49073|35.88001
S|(Tell el-Husniya)|33.32138|44.36734
S|(Tell el-Ibadi)|35.24195|36.77368
S|(Tell el-Ifshar / Tel Hefer)|32.37224|34.90819
S|(Tell el-Iswid)|30.87126|31.77671
S|(Tell el-Jabiyé)|32.91961|36.00034
S|(Tell el-Jaf'a)|34.99574|36.59954
S|(Tell el-Jidr)|31.77805|46.49466
S|(Tell el-Jijan)|36.41266|37.34130
S|(Tell el-Ginn)|30.91917|32.05040
S|(Tell el-Jisr)|33.63981|35.77854
S|(Tell el-Judaideh)|36.26750|36.58660
S|(Tell el-Kalaiya)|34.72314|36.86613
S|(Tell el-Kawilyat)|32.05138|45.81784
S|(Tell el-Kabir)|36.43643|38.26642
S|(Tell el-Kabr)|34.12877|44.37104
S|(Tell el-Kawa)|31.58899|46.19688
S|(Tell el-Kebir)|34.59840|36.52741
S|(Tell el-Kerkh)|35.81992|36.46516
S|(Tell el-Khamra)|33.02512|44.23777
S|(Tell el-Khan)|36.30937|43.54430
S|(Tell el-Kharaze)|33.37607|36.47228
S|(Tell el-Khazna)|36.48489|40.35130
S|(Tell el-Khazna)|35.55203|36.91671
S|(Tell el-Kheleifeh)?|29.54612|34.98242
S|(Tell el-Khirab)|32.17084|35.27502
S|(Tell el-Khiyara)|33.68923|35.84765
S|(Tell el-Khodor)??|32.70295|36.12819
S|(Tell el-Khwain)?|36.04251|43.08621
S|(Tell el-Koum?)??|33.15550|35.90835
S|(Tell el-Laham H1230-1231)|32.05045|45.40625
S|(Tell el-Madbaha)|32.88902|44.18881
S|(Tell el-Madir)|32.32361|44.99980
S|(Tell el-Majouz)|34.86265|36.81383
S|(Tell el-Majruḥ)|35.01126|36.66470
S|(Tell el-Mal)??|33.12976|35.98822
S|(Tell el-Malkha)|31.36615|44.92887
S|(Tell el-Malqaṭ)|31.98108|44.93493
S|(Tell el-Mantar)|35.29074|36.69912
S|(Tell el-Masṭah esh-Shamali)|36.11095|42.45236
S|(Tell el-Mas'ud A026)|33.64365|44.18573
S|(Tell el-Mas'ud Sharqi A028)|33.62345|44.21274
S|(Tell el-Maut)|32.50126|44.49506
S|(Tell el-Mesk)|31.28612|30.82062
S|(Tell el-Mu'alam D859)|32.70571|45.42561
S|(Tell el-Muhaffar)|32.44253|35.21776
S|(Tell el-Mujelibah D84)|33.71888|44.50346
S|(Tell el-Mujelibah D85)|33.71374|44.50047
S|(Tell el-Muraydiyah K29)|32.70674|44.53094
S|(Tell el-'Omriyeni)|36.15819|42.97182
S|(Tell el-Ouard Sharqi)|36.79919|40.34443
S|(Tell el-'Oueili)|31.24285|45.88542
S|(Tell el-Qama)|34.36637|41.08772
S|(Tell el-Qoubli)|36.09386|37.12647
S|(Tell el-Qrassi)|34.64682|36.52280
S|(Tell el-Tawwil)|31.24460|45.87546
S|(Tell el-'Ubaid)|30.97228|46.03061
S|(Tell el-Udwaniya)|36.27462|39.04593
S|(Tell el-'Umayri)|31.86856|35.88823
S|(Tell el-Umfuggar A072)|32.90587|44.39154
S|(Tell el-Uwaynat 15)|36.70342|42.36136
S|(Tell el-Uwaynat West)|36.69932|42.38422
S|(Tell el-'Uyun)?|34.16095|36.27429
S|(Tell el-Wasmah)?|34.81244|36.96713
S|(Tell el-Wasta)|36.61345|39.26520
S|(Tell el-Wawiya)|34.62382|36.56249
S|(Tell en-Nabariz)|35.92118|36.88852
S|(Tell en-Najmi)|31.74052|46.77387
S|(Tell en-Nasbeh)|31.88537|35.21648
S|(Tell en-Nashabiyah)|33.52559|36.48783
S|(Tell en-Nasriya)|35.23104|36.65680
S|(Tell en-Nasriya)|31.49994|46.04274
S|(Tell en-Nijmah)|32.17799|35.28156
S|(Tell en-Nis)|36.20801|41.88052
S|(Tell-e Nurabad)|30.12201|51.52072
S|(Tell Ermen / Kızıltepe)|37.19212|40.58908
S|(Tell er-Rafir)|36.57334|37.99678
S|(Tell er-Rahmaniya)|36.18962|42.80275
S|(Tell er-Ramadi)|34.64787|40.87625
S|(Tell er-Rasafah)|31.78320|46.36120
S|(Tell er-Rasas el-Kabir)|32.81761|44.93572
S|(Tell er-Rashidiya)?|33.23673|35.21617
S|(Tell er-Rishayd K90)|32.74893|44.76866
S|(Tell er-Rotab)|30.54826|31.96367
S|(Tell er-Rum)|35.43946|40.11320
S|(Tell esh-Shaar)??|33.17354|35.94411
S|(Tell esh-Shair)|36.15035|42.46676
S|(Tell esh-Shams)??|33.25027|35.99516
S|(Tell esh-Shaur)|36.49710|42.13842
S|(Tell esh-Shaureh)|34.35256|45.01787
S|(Tell esh-Sheikh)|35.07467|36.77771
S|(Tell esh-Sheikha?)??|33.18559|35.79336
S|(Tell esh-Sheikh Sultan)|35.47690|36.43513
S|(Tell esh-Sheir)|35.91408|43.35543
S|(Tell esh-Shiba)|36.24656|42.60573
S|(Tell esh-Shihab)?|32.69176|35.96846
S|(Tell esh-Shihan)|32.87981|36.61396
S|(Tell esh-Shikh)|36.06159|36.92824
S|(Tell esh-Shir)|35.19936|36.62249
S|(Tell esh-Shiyukh Tahtani)|36.75419|38.08398
S|(Tell esh-Shor)|35.59756|37.19471
S|(Tell esh-Shuor Gharbi)|36.84491|40.45635
S|(Tell esh-Shuor Sharqi)|36.85917|40.48614
S|(Tell esh-Shunah)|32.63475|35.57580
S|(Tell-e Spid)|30.25209|51.48439
S|(Tell Sa'ad D115-116)|33.67726|44.53461
S|(Tell es-Sa'adin)?|34.77945|36.84404
S|(Tell es-Sabahiya)|32.56320|44.43260
S|(Tell es-Sadan)|32.88520|44.80977
S|(Tell es-Safi)|35.09683|37.22122
S|(Tell es-Safir)|34.82505|36.79793
S|(Tell es-Sahal)|36.50067|41.42639
S|(Tell es-Sahlan)|36.58506|38.99526
S|(Tell es-Sara)|36.81577|41.98264
S|(Tell es-Sarah)|34.26822|45.00228
S|(Tell es-Sahneh K139)|32.48692|44.52999
S|(Tell es-Said Mansur K114)|32.66135|44.38193
S|(Tell es-Sakan)|31.47476|34.40527
S|(Tell eṣ-Ṣakhar D211)|33.43770|44.40484
S|(Tell es-Sakheri)|31.00958|46.03787
S|(Tell es-Salat)?|35.30242|36.35141
S|(Tell eṣ-Ṣaliḥiyeh / Tell Farzat)|33.50873|36.46960
S|(Tell es-Saman)|36.21167|38.98779
S|(Tell es-Saman Sharqi)|36.20118|38.99932
S|(Tell es-Samen)|36.42800|42.67900
S|(Tell es-Samene)??|32.86060|35.99790
S|(Tell es-Samir)|36.75216|42.16582
S|(Tell es-Sasi)|31.35164|30.77910
S|(Tell es-Sawwan)|34.12099|43.90494
S|(Tell es-Sawwan)|36.35275|39.06413
S|(Tell es-Sawwan)|33.58597|36.48640
S|(Tell es-Sefin / Sefinet-Nebi-Nouh)|34.57745|36.54353
S|(Tell eṣ-Ṣeghir)|34.60154|36.52400
S|(Tell es-Seidi)|30.89736|32.19079
S|(Tell es-Seur)|34.59248|36.53579
S|(Tell es-Silla)|34.68787|36.84313
S|(Tell eṣ-Ṣimdi)|32.13202|35.48858
S|(Tell es-Sin)|35.31937|40.25024
S|(Tell es-Sirhan)|33.78922|35.94306
S|(Tell es-Sour)|34.81568|37.16280
S|(Tell es-Su'aydan K145)|32.49273|44.63800
S|(Tell es-Subaykhi)|33.90591|45.08284
S|(Tell es-Subba)|32.59328|35.94738
S|(Tell es-Sulma)|32.22190|46.23411
S|(Tell es-Sultan)|33.40653|36.40154
S|(Tell es-Sumayr)|36.06859|42.68943
S|(Tell es-Sus)?|34.97829|36.86487
S|(Tell es-Sus)?|36.45043|40.39662
S|(Tell es-Sweyhat)|36.27408|38.25390
S|(Tell eṭ-Ṭabal)?|32.17795|46.76667
S|(Tell et-Tash)|36.81096|41.84723
S|(Tell et-Tawila)|31.84893|46.81848
S|(Tell eṭ-Ṭelliya)|31.17942|45.45228
S|(Tell ez-Zabali)|31.76168|46.73697
S|(Tell ez-Zara'ah?)??|33.37249|36.27931
S|(Tell Fadġami)|35.91186|40.87074
S|(Tell Fadkhiliya?)|36.50894|43.26481
S|(Tell Fadous-Kfarabida)|34.22415|35.65516
S|(Tell Fadul)|36.03441|41.63384
S|(Tell Fafine)|36.34861|37.24286
S|(Tell Fahl)|31.53085|45.93180
S|(Tell Failoun)|35.93543|36.52674
S|(Tell Fakhar H1090)|32.02552|45.33969
S|(Tell Fakhkhar)?|35.38142|43.97898
S|(Tell Faqqus)?|35.94757|38.17393
S|(Tell Farawa U196)|31.64402|45.86520
S|(Tell Fares)|37.01347|41.15935
S|(Tell Fares esh-Sharqi)|36.74189|41.06838
S|(Tell Farfara)|36.81995|40.50538
S|(Tell Fayr)|36.59577|41.07910
S|(Tell Fazara)??|33.01731|35.83090
S|(Tell Fiden)|35.36333|40.56285
S|(Tell Frach)?|34.71308|36.12501
S|(Tell Freji)|35.52627|36.83547
S|(Tell Fursan)|36.72746|37.70431
S|(Tell Gannaṣ)|33.06759|44.32603
S|(Tell Gazal)|35.74066|36.41136
S|(Tell Gazali)|35.00015|37.05945
S|(Tell Gelsenah A061)|33.05070|44.43097
S|(Tell Germez)|34.17868|44.98639
S|(Tell Ghamqa)?|34.87237|35.88625
S|(Tell Ghanamat)|36.67413|37.80196
S|(Tell Ghanem el-'Ali)|35.77807|39.42019
S|(Tell Ghani)|36.57611|41.87609
S|(Tell Ghasil)|33.92031|36.07146
S|(Tell Ghazal)|36.82282|40.65857
S|(Tell Ghazal Fawqani)|36.78809|40.50471
S|(Tell Ghazza)|33.66813|35.82478
S|(Tell Ghiraba)??|33.10525|36.16425
S|(Tell Ghizlanieh)|33.39145|36.45389
S|(Tell Ghubain)|36.66414|42.18175
S|(Tell Gomel)|36.59236|43.48119
S|(Tell Göz Giran)|37.00637|42.40050
S|(Tell Greifat)|36.91192|41.84369
S|(Tell Greza)|35.39058|45.75939
S|(Tell Gubba)|34.19146|44.99620
S|(Tell Guli)|36.52423|41.39962
S|(Tell Gumaiyima)|30.89250|31.88708
S|(Tell Habesh)|37.07821|40.90833
S|(Tell Hablat)|31.48721|46.38657
S|(Tell Habuba Kabira)|36.16311|38.06280
S|(Tell Hadad)|34.19273|45.05665
S|(Tell Hadari)|33.09481|44.31677
S|(Tell Haddad)|36.86170|41.71638
S|(Tell Hadhail)|36.14979|42.05445
S|(Tell Hadi)|36.87041|41.86493
S|(Tell Haikal)|35.59722|43.27247
S|(Tell Hailan)|36.29257|37.20447
S|(Tell Hajar)|37.01869|41.67890
S|(Tell Hajbah)|34.90025|36.89897
S|(Tell Hajeb)|36.85072|38.43849
S|(Tell Hajir)|36.93480|40.73446
S|(Tell Hajji Badr)|36.97841|41.22767
S|(Tell Halabiya)|33.14725|44.32913
S|(Tell Halajak / Tell Baddaye)|36.73227|38.11938
S|(Tell Halawa)|36.11860|38.09240
S|(Tell Halawa D229)|33.42584|44.48721
S|(Tell Halawa)|35.47646|37.15097
S|(Tell Halim Asra Hajin)|34.68268|40.83267
S|(Tell Hallaq)|37.07681|41.89622
S|(Tell Halula)|36.42300|38.18212
S|(Tell Hamamiyat)|35.38084|36.53672
S|(Tell Hamam Gharbi)|36.56801|40.32497
S|(Tell Hamam Sharqi)|36.55002|40.35884
S|(Tell Haman)|36.72619|41.61193
S|(Tell Hamar)|36.79088|40.74168
S|(Tell Hamayma H1152)|32.18251|45.53608
S|(Tell Hamdun)|37.10978|40.84475
S|(Tell Hamed)|32.82380|36.12114
S|(Tell Hamida)|36.72377|42.22732
S|(Tell Hammam U183)|31.63605|45.76969
S|(Tell Hammoud)|36.79235|39.85604
S|(Tell Hamoukar)|36.81276|41.95597
S|(Tell Hana)|34.93378|37.03804
S|(Tell Hanifa)|35.03418|36.87565
S|(Tell Hanoua)|36.85048|40.63496
S|(Tell Hanta)|36.51825|41.03656
S|(Tell Haourane)|32.92645|36.05056
S|(Tell Harba A001)|33.99037|44.10392
S|(Tell Harbi A105)|32.87029|44.57713
S|(Tell Harmaz)|36.56475|40.55625
S|(Tell Haruna)|36.47807|42.50850
S|(Tell Hasanuçağı)|36.31764|36.42722
S|(Tell Hasna)|36.40921|40.83626
S|(Tell Hassane)|35.83277|36.47651
S|(Tell Hassane Pasha)|34.90781|37.06640
S|(Tell Hassan Kief)|36.47950|43.02714
S|(Tell Hassek)|36.77279|40.56209
S|(Tell Hassuna)|36.06810|43.21879
S|(Tell Hatihat el-Gharbi)|33.00574|44.41760
S|(Tell Hatulu)|36.91223|40.82073
S|(Tell Hawda)|36.70200|41.61909
S|(Tell Hayal)|36.80242|42.17830
S|(Tell Haziqa?)|33.05376|35.85050
S|(Tell Helif)|37.13862|40.83877
S|(Tell Hellab)?|36.26630|43.13179
S|(Tell Herada)|36.23850|42.79866
S|(Tell Hermel)|36.90898|40.36222
S|(Tell Hijana)|33.35261|36.54885
S|(Tell Hisham)|32.20709|44.43935
S|(Tell Hiyamiyat)|33.06873|44.44596
S|(Tell Hrim)|35.20015|40.33891
S|(Tell Hudhud)?|36.58431|38.00638
S|(Tell Humadi A129)|32.83266|44.63980
S|(Tell Humeida)|35.76409|39.69823
S|(Tell Huqna)|36.55813|42.55832
S|(Tell Husan)|36.62859|42.09002
S|(Tell Husen)|35.63610|40.72553
S|(Tell Husn)|32.44742|35.61591
S|(Tell Hutlayfa K125)|32.61758|44.39358
S|(Tell Huways)?|35.40917|37.12580
S|(Tell Huwen)|36.42325|40.86118
S|(Tell Ḥwesh)?|36.54793|40.75661
S|(Tell Ibn esh-Shabab)|36.66464|38.94963
S|(Tell Ibrahim Awad)|30.84952|31.83011
S|(Tell Ibrahim el-Khalil)|32.39358|44.34745
S|(Tell Ibwan / Naggarein)|31.33461|31.78991
S|(Tell-i Ghazir)|31.36018|49.41253
S|(Tellik)|36.78056|38.10726
S|(Tell Iktanu)|31.81909|35.67148
S|(Tell Imlihiyeh)|34.20365|44.99175
S|(Tell Ilbol)|36.59458|37.18879
S|(Tell Imriyah A115)|32.81341|44.59197
S|(Tell Ishaqi I A059)|33.08189|44.35504
S|(Tell Ishaqi II)|33.08721|44.34456
S|(Tell Ishnayt A015)|33.77530|44.28966
S|(Tell Itwaybah A077)|32.81216|44.40572
S|(Tell Izhane)|35.94230|36.48669
S|(Tell Jaddalah 'Uliah)|35.81829|43.10753
S|(Tell Jaddu)|36.51160|42.54199
S|(Tell Jadidah)|34.01568|42.46452
S|(Tell Jalul)|31.71911|35.85610
S|(Tell Jaluqah 1-2)|36.65248|42.93710
S|(Tell Jamil)|36.68289|40.60699
S|(Tell Jamous)|34.66878|36.12938
S|(Tell Jamous)|36.69946|41.60969
S|(Tell Jamus)|36.79683|40.18995
S|(Tell Jarnia)|36.16408|38.23487
S|(Tell Jarra)|32.05520|44.71081
S|(Tell Jassas)?|36.58532|40.68600
S|(Tell Jawa)|31.85766|35.93169
S|(Tell Jawa)|32.33563|37.00387
S|(Tell Jawan I)|33.07300|44.28127
S|(Tell Jawan II)|33.07806|44.28267
S|(Tell Jawan IV)|33.07400|44.27272
S|(Tell Jebarah)|30.74462|46.50668
S|(Tell Jeddawi)|36.85222|41.77507
S|(Tell Jededah)|30.75490|46.59951
S|(Tell Jellad)|36.58377|40.70873
S|(Tell Jemmeh)|31.38716|34.44512
S|(Tell Jibrin)|35.17256|36.78822
S|(Tell Jidlah)|36.65866|38.95259
S|(Tell Jidr K144)|32.46638|44.60782
S|(Tell Jidriya)?|36.93219|42.30197
S|(Tell Jiejya)|36.73806|40.08510
S|(Tell Jifar)|35.41887|36.43853
S|(Tell Jihan)|37.07235|41.45322
S|(Tell Jikan)|36.65467|42.90291
S|(Tell Jira / Tell el-Jern)|36.13767|43.00079
S|(Tell Jouweif SS 8)|36.25665|38.19922
S|(Tell Jubb el-Bahra)|34.73438|40.80372
S|(Tell Judayda)|36.43205|40.85690
S|(Tell Jul Bustan Foqani)|36.85728|40.96229
S|(Tell Jum'a)|36.66323|40.34212
S|(Tell Kadrich)|36.58351|37.34343
S|(Tell Kaffin)|36.41642|37.04682
S|(Tell Kahaf)|36.78054|41.14030
S|(Tell Kalb el-Tash)|36.76411|41.84099
S|(Tell Karmine)|36.47201|37.06035
S|(Tell Kammaz D850)|32.84266|45.33683
S|(Tell Kanbar)?|36.22347|40.77534
S|(Tell Karadurmuşlu)|36.46941|36.40525
S|(Tell Karm)|37.06921|40.75410
S|(Tell Karma)|33.03349|44.41060
S|(Tell Karuk / Ishan Suraysur K96)|32.67175|44.84382
S|(Tell Kasalat)|35.01246|36.88317
S|(Tell Kashkashok III)|36.63686|40.64144
S|(Tell Kasir / Sayid Azim)|32.73038|44.31124
S|(Tell Kawkab)|33.40498|36.16357
S|(Tell Kayf / Tel Keppe)|36.49086|43.12262
S|(Tell Kazan)?|35.18294|44.04476
S|(Tell Kazhaw)|35.38046|45.64945
S|(Tell Keçebey)|36.28596|36.30711
S|(Tell Keif)|37.09053|41.09165
S|(Tell Keisan)|32.87310|35.15082
S|(Tell Keleş)|36.25965|36.50303
S|(Tell Kerma)|36.44809|40.83724
S|(Tell Kesaran)|34.28386|44.99885
S|(Tell Khabbi)|36.87076|40.53752
S|(Tell Khodr)|36.72572|41.43646
S|(Tell Khadr)?|35.03695|37.03191
S|(Tell Khajeir)|36.91484|41.65039
S|(Tell Khalil)|36.37269|40.68693
S|(Tell Khallaweh)|34.37473|44.99204
S|(Tell Khama)|34.99955|44.39395
S|(Tell Khamis)|36.75634|41.40141
S|(Tell Khanasri)|32.39336|36.04652
S|(Tell Khantra)|31.69051|46.02822
S|(Tell Khanzir)|35.43284|36.96175
S|(Tell Khanzir)|36.75454|39.83701
S|(Tell Khanzir)|36.83742|40.89033
S|(Tell Khanzir Fawqani)|36.99417|42.20764
S|(Tell Kharabeh Shattani)|36.62133|42.90309
S|(Tell Kharbud)|34.28574|45.00408
S|(Tell Khardal?)|36.97687|42.26103
S|(Tell Kharima)|36.25435|42.67238
S|(Tell Kharima?)|31.52780|45.42253
S|(Tell Kharnoub)|36.74997|41.32459
S|(Tell Kharnub)|37.06606|41.38530
S|(Tell Kharun)|34.68728|36.76375
S|(Tell Khas)|36.96244|40.61439
S|(Tell Khatun)|36.78043|40.63087
S|(Tell Khathir)?|36.27993|42.77082
S|(Tell Khayran)|35.03786|44.20421
S|(Tell Khazna EPAS 45)|36.10469|43.79216
S|(Tell Khazna I)|36.66125|40.89547
S|(Tell Khazna Jawwani)|36.65181|40.89237
S|(Tell Khazna Takhtani)|36.62814|40.84567
S|(Tell Khidr)|36.54840|42.64779
S|(Tell Khoshi)|36.19290|41.83453
S|(Tell Khuair)|35.35968|36.74022
S|(Tell Khumayma)|36.18537|37.63745
S|(Tell Khurada)??|33.06079|35.84622
S|(Tell Khuwaish)|35.59360|43.23111
S|(Tell Khuzna)|32.30579|44.50342
S|(Tell Kiber 2)|36.66086|42.22651
S|(Tell Kidkan)|36.72690|39.98581
S|(Tell Kinj)|34.31528|44.98301
S|(Tell Kirab)|36.96218|41.88532
S|(Tell Kiri)|34.59792|36.03931
S|(Tell Klaia)|36.77356|40.06426
S|(Tell Knediǧ)|36.35173|40.79156
S|(Tell Kosak Shamali)|36.55761|38.27977
S|(Tell Kotchek Saghir)|36.81895|42.05427
S|(Tell Koulie)|36.72183|37.82236
S|(Tell Kulu)|36.75345|41.04491
S|(Tell Kundariya)|36.74619|37.89189
S|(Tell Kurdu)|36.33003|36.44489
S|(Tell Kurma)|36.14781|41.83497
S|(Tell Kurr A045)|33.58328|44.26895
S|(Tell Kusakh)?|33.77028|45.31860
S|(Tell Labwa I-II esh-Shamal)|34.19874|36.35063
S|(Tell Labwa III el-Yamin)|34.19479|36.34845
S|(Tell Laha)?|34.69003|35.96914
S|(Tell Lashkry)|36.18189|44.13215
S|(Tell Latmin)|35.36033|36.65419
S|(Tell Ma'az)|36.75506|41.12457
S|(Tell Mabtouha)|35.62104|36.36903
S|(Tell Mabtuh)|36.47700|40.14187
S|(Tell Mabtuh esh-Sharqi)|36.50683|40.45628
S|(Tell Madan)|34.91931|44.37726
S|(Tell Madhhur)|34.36237|45.01906
S|(Tell Mafash)|36.32446|38.98904
S|(Tell Maghar)|35.21575|44.30380
S|(Tell Maghas)|36.61291|40.39203
S|(Tell Maghrat Ghazir)|31.55306|34.58660
S|(Tell Magrin)|36.83210|39.04179
S|(Tell Mahmudiyah A060)|33.06555|44.36647
S|(Tell Mahmutlu)|36.50287|36.39177
S|(Tell Mahuz)|35.49156|43.83660
S|(Tell Majarin)|36.35810|42.71699
S|(Tell Majbad)|32.73957|44.39733
S|(Tell Majdalun)|33.99650|36.12212
S|(Tell Majid SRP 39)|34.51598|45.26046
S|(Tell Majnuna)|36.67443|41.05372
S|(Tell Makhad er-Rejba)|36.58920|40.74951
S|(Tell Makharum)|36.35927|40.62338
S|(Tell Maksour)|35.30955|36.35199
S|(Tell Maksur)|36.24007|37.45779
S|(Tell Maled)|36.44547|37.22873
S|(Tell Malha)?|35.68194|43.04950
S|(Tell Mallaha)|33.09010|35.58182
S|(Tell Mana'a)|36.68129|42.14424
S|(Tell Manzil)|34.71848|44.73896
S|(Tell Maqasaba)|31.50119|30.74151
S|(Tell Marag)|36.60111|42.52773
S|(Tell Maraq)|35.44323|36.84578
S|(Tell Marqada)|35.74444|40.76686
S|(Tell Marwaniye)|34.86700|40.66274
S|(Tell Masa'ud)|34.85916|36.93229
S|(Tell Mashara)|33.13143|35.95733
S|(Tell Mashnaka)|36.29005|40.79282
S|(Tell Mashrah)|34.89901|44.37105
S|(Tell Ma'shuq)|37.06067|41.68737
S|(Tell Massin)|35.31004|36.72084
S|(Tell Massud el-Rafiya)|36.87522|42.03527
S|(Tell Masti)|36.79562|41.20630
S|(Tell Mas'ud)|33.98236|36.07189
S|(Tell Matariya)|36.29850|40.77462
S|(Tell Mathkhuriyah)|30.99787|46.06144
S|(Tell Matubis)|31.28640|30.55602
S|(Tell Matul)|31.45296|45.41942
S|(Tell Mawfali)|36.11796|41.83999
S|(Tell Mazaale)|36.73397|37.94508
S|(Tell Mazar)|32.22198|35.60616
S|(Tell Mbarakat)|35.12610|36.87772
S|(Tell Me'ebid)|31.16422|32.19119
S|(Tell Mejdel)|36.53973|40.61409
S|(Tell Meldah)|36.25463|42.86502
S|(Tell Melebiya)|36.40526|40.81166
S|(Tell Merim)??|33.21208|36.08080
S|(Tell Merqab Abu Ṭair)|36.12214|41.42932
S|(Tell Meskan)|36.76726|40.08263
S|(Tell Metkin / Metnin)|35.11224|36.64820
S|(Tell Midraj)|36.08604|42.82311
S|(Tell Millis)|36.00417|36.48285
S|(Tell Mirza H1193)|32.11190|45.55021
S|(Tell Miskin A004)|33.82369|44.24543
S|(Tell Mithlay)|36.75870|42.13756
S|(Tell Mizan)|31.23653|45.83611
S|(Tell Mouerik Foqani)|36.70267|40.77564
S|(Tell Mouerik Jowani)|36.67524|40.77492
S|(Tell Mounbateh)|36.35939|39.05661
S|(Tell Mouslimiye)|36.31652|37.21523
S|(Tell Msiyah)|36.37737|40.81069
S|(Tell Muezer?)|36.25731|40.33473
S|(Tell Mugaizir)|32.36283|45.73885
S|(Tell Mughaisil D658)|33.20675|45.31442
S|(Tell Mugharat esh-Sharqi H900)|32.27313|45.60201
S|(Tell Mughr)|36.47759|40.24495
S|(Tell Muhammed)|33.30057|44.46821
S|(Tell Muhammed K117)|32.63932|44.38471
S|(Tell Muhammed 'Ali)|36.66192|41.22904
S|(Tell Mohammed 'Arab)|36.63456|42.88987
S|(Tell Muhammad Kabir)|36.91064|41.17370
S|(Tell Mujarja)|36.51680|40.70077
S|(Tell Mulayfat)|36.31087|43.54243
S|(Tell Mulla Matar)|36.45034|40.83297
S|(Tell Murbat Abu Khazir)|35.25695|44.01115
S|(Tell Muraibi)|31.38745|45.05570
S|(Tell Mureybet)|36.06893|38.09208
S|(Tell Murhish K28)|32.72713|44.51108
S|(Tell Murshudi)|36.59323|41.19013
S|(Tell Mutlaq)?|36.92846|42.22173
S|(Tell Naban)|36.87784|40.60337
S|(Tell Nader EPAS 5)|36.17315|44.07549
S|(Tell Nagila)|31.50265|34.75839
S|(Tell Naim Kabir)|36.77593|41.47040
S|(Tell Naim Ṣaghir)|36.74815|41.47755
S|(Tell Namliya)?|35.43979|40.63544
S|(Tell Naqurtaya)|36.29334|43.37587
S|(Tell Nashwein)|31.35484|30.87624
S|(Tell Na'ur)|36.75105|41.91797
S|(Tell Neaz / Newaz)|36.12556|36.76363
S|(Tell Nef)?|36.41498|37.28492
S|(Tell Nimrin / Tell esh-Shuna)|31.90077|35.62501
S|(Tell Nimrud A078)|32.79382|44.46560
S|(Tell Nimrud K26)|32.76060|44.51255
S|(Tell Nisr)|36.95277|41.37499
S|(Tell Noquaira)|34.66304|36.68003
S|(Tell Noubbol)|36.37720|36.99613
S|(Tell Nourek)|36.68279|40.88750
S|(Tell Nufeji)|31.35396|45.64076
S|(Tell Othman SS 20A)|36.24716|38.24339
S|(Tell Qabr el-Jumaili)|32.80054|44.81546
S|(Tell Qabrit)|31.22420|30.59934
S|(Tell Qadimiya)|36.74685|41.27490
S|(Tell Qal'a)|35.65559|36.67130
S|(Tell Qal'a Badyar H1399)|31.86426|45.47176
S|(Tell Qalinj Agha EPAS 3)|36.17688|44.01414
S|(Tell Qaramel)|36.37775|37.27507
S|(Tell Qarassa)|36.83127|41.46106
S|(Tell Qarrasa)?|32.83030|36.41521
S|(Tell Qarta)|36.83268|40.22903
S|(Tell Qasile)|32.10157|34.79502
S|(Tell Qasr Alloj)|36.55652|42.37158
S|(Tell Qasrin es-Saghir)|33.33559|36.54921
S|(Tell Qatina)|34.65541|36.61692
S|(Tell Qattina)|36.80144|40.05909
S|(Tell Qirdishan)|36.58261|42.34018
S|(Tell Qlay'a)|36.67477|39.66862
S|(Tell Qoz)|36.80800|41.77773
S|(Tell Qrin)??|33.16174|36.05925
S|(Tell Qsubi)|35.73874|39.76499
S|(Tell Qubasin)|36.43312|37.57267
S|(Tell Qubr Abu el-'Atiq)?|35.76285|39.78399
S|(Tell Quliya)|36.96947|40.77710
S|(Tell Qumluk / Tell Zeruk)|36.70127|38.08747
S|(Tell Qunaytirah)|37.03009|41.88206
S|(Tell Qurayšun)|33.06595|44.33828
S|(Tell Qurghan)|35.83210|44.08404
S|(Tell Ousha' D16)|33.97844|44.80371
S|(Tell Qushla)|36.77168|41.13535
S|(Tell Rabun)?|35.09399|36.82429
S|(Tell Rad Shaqrah)|36.46782|40.83250
S|(Tell Raffan)|36.71642|42.80069
S|(Tell Raqa'i)|36.44022|40.85226
S|(Tell Rahhal)|36.34356|37.38771
S|(Tell Rajab)|36.71021|40.59752
S|(Tell Rajman)|36.49140|40.80400
S|(Tell Ramal)|33.26345|44.27022
S|(Tell Rashidiya)|36.12017|40.70272
S|(Tell Rayyaq)?|33.85413|36.02053
S|(Tell Razayanah)|36.48827|43.19301
S|(Tell Razuk)|34.34668|44.97802
S|(Tell Rikrak)|36.17833|42.73782
S|(Tell Rishad D558)|33.23738|44.54396
S|(Tell Rumah)|31.83821|45.50154
S|(Tell Rumaylan)|36.94838|41.96988
S|(Tell Rumdhaniya)|35.63700|43.01359
S|(Tell Rumman)|36.57365|40.48145
S|(Tell Sa'ad F3)|29.42966|48.27623
S|(Tell Sa'adiya Sharqi)|35.73897|42.91285
S|(Tell Sa'adun)|36.79877|41.62407
S|(Tell Sabaine)|36.12150|37.51515
S|(Tell Sabi Abyad)|36.50357|39.09293
S|(Tell Sabkha)|35.09200|37.06941
S|(Tell Sabra)|34.20670|45.01228
S|(Tell Sa'diya / Gardem)|37.02766|41.62316
S|(Tell Ṣafar)|35.22734|44.31244
S|(Tell Saff el-Gharbi A048)|33.43054|44.30867
S|(Tell Saff esh-Sharqi A049)|33.42451|44.31912
S|(Tell Safra)|36.80173|40.02115
S|(Tell Safroun)|34.73936|36.03156
S|(Tell Safur)|36.91063|40.49997
S|(Tell Sahar)|34.27564|45.07341
S|(Tell Sa'id F6)|29.43324|48.27839
S|(Tell Sa'ir)|36.90237|38.30192
S|(Tell Sakar)|36.95039|40.70071
S|(Tell Sakarja)|34.49764|36.50909
S|(Tell Sakheriya / Tell Abu Ba'arura E20)|30.97867|46.16846
S|(Tell Sakiya)|36.13791|41.62468
S|(Tell Sakka)|33.44032|36.46842
S|(Tell Sakr)|35.41447|36.50220
S|(Tell Salandar)|36.86342|40.79902
S|(Tell Sali')|32.74308|44.40321
S|(Tell Salihiyyah)|36.24022|36.46359
S|(Tell Samir 5)|36.72371|42.17105
S|(Tell Sangar)|31.49939|30.91953
S|(Tell Sanhur)|30.96517|32.01624
S|(Tell Sara)|36.69216|40.95551
S|(Tell Sarin)|32.88635|44.51754
S|(Tell Sawadih)|36.82955|40.51601
S|(Tell Sayba)|36.02980|42.73515
S|(Tell Sebael)|34.55016|36.03090
S|(Tell Seker al-Aheimar)|36.66695|40.31000
S|(Tell Sekar Fawqani)|36.84754|40.59444
S|(Tell Sekar Tahtani)|36.80683|40.60157
S|(Tell Sekar Wastani)|36.82711|40.59675
S|(Tell Selenkahiye)|36.09781|38.05192
S|(Tell Sengor A)|34.18895|45.00115
S|(Tell Sfeir)|36.61310|37.41849
S|(Tell Ṣfuk)|36.05974|41.25627
S|(Tell Sha'bu)?|36.67055|42.95969
S|(Tell Shaddada)|36.03758|40.74923
S|(Tell Shahal)?|31.62961|45.23891
S|(Tell Sha'ir)|37.05275|41.43727
S|(Tell Sha'ir)|37.06652|41.12017
S|(Tell Sha'ir 'Askar)|36.26645|36.53127
S|(Tell Shais)|31.16166|46.04150
S|(Tell Shakhin)|36.31951|39.00384
S|(Tell Shalem)|32.39899|35.52608
S|(Tell Shamma)|36.67339|40.80954
S|(Tell Shams ed-Din Tannira T 562)|36.24197|38.14731
S|(Tell Sharisi)|36.89195|41.36567
S|(Tell Sheikh)??|33.25901|36.13731
S|(Tell Sheikh 'Ali)?|33.55064|36.47535
S|(Tell Sheikh Amin)|36.76229|40.72607
S|(Tell Sheikh Hasan)|36.20224|38.11432
S|(Tell Sheikh Hassan)|36.32723|39.05240
S|(Tell Sheikh Muhammed)|35.52921|36.37851
S|(Tell Sheikh Muhammed)?|34.26220|44.18533
S|(Tell Sheikh Nims)|36.78614|41.13988
S|(Tell Sheir)|35.42800|43.55945
S|(Tell Sh'eirat)|34.48854|36.94782
S|(Tell Shelgiyya)|37.02423|42.38030
S|(Tell Shermola)|37.09725|40.92947
S|(Tell Shikhan)|36.04892|42.90343
S|(Tell Shmit U168)|31.74730|45.83243
S|(Tell Shughliyat)?|32.38312|47.13301
S|(Tell Shulayt)|32.75558|44.06904
S|(Tell Shuraq)|36.93545|41.20680
S|(Tell Sidi-Ala)|35.48684|36.74162
S|(Tell Sikkin Qa'ade)|35.24065|36.46965
S|(Tell Sikkin Sarut)|35.16110|36.58404
S|(Tell Sikne)|31.39355|45.84235
S|(Tell Sinker A016)|33.79723|44.32385
S|(Tell Siran)|32.01055|35.87573
S|(Tell Sirawl)|36.16043|42.70013
S|(Tell Sirhan)|33.43930|43.94045
S|(Tell Sitak)|35.64208|45.50295
S|(Tell Sleimane)?|33.55515|36.45738
S|(Tell Sleimani)|36.57227|40.76192
S|(Tell Sna)|35.12133|37.11900
S|(Tell Sourane)|36.56643|37.21078
S|(Tell Suffane)|35.99286|36.69262
S|(Tell Suhairi U242)|31.47442|45.58783
S|(Tell Sukayk)|35.41345|36.78977
S|(Tell Sukheri H1417)|31.93183|45.54085
S|(Tell Sulayhat)|32.32028|35.58684
S|(Tell Suran)?|35.28714|36.72206
S|(Tell Suran)|36.26414|37.37444
S|(Tell Susian)|36.43462|37.44224
S|(Tell Suwwar)|35.50987|40.66152
S|(Tell Taafliye)|36.68093|37.69778
S|(Tell Tabl D627)|33.21937|44.90997
S|(Tell Ṭaḥīm)|31.79223|46.02255
S|(Tell Tahin)|36.80461|41.58889
S|(Tell Tahir)|36.00157|42.75426
S|(Tell Taïbet el-Ism)|35.32032|36.86296
S|(Tell Tair)|37.03955|40.70323
S|(Tell Talab)|36.74487|42.20145
S|(Tell Ta'lbaya)?|33.81860|35.87022
S|(Tell Tamak)|35.17163|37.04309
S|(Tell Tamir)|36.65893|40.36509
S|(Tell Tamr)|36.82176|41.90622
S|(Tell Tanjero)|35.47604|45.42607
S|(Tell Tannura)|34.34784|44.96531
S|(Tell Tarbas)|31.73628|45.87120
S|(Tell Ṭarṭab Kabir)|37.01291|41.23203
S|(Tell Tartab Saghir)|37.00984|41.23971
S|(Tell Tarzi Tahtani)|36.91994|40.80331
S|(Tell Tawil)?|36.52129|36.85925
S|(Tell Tawil)|33.37411|36.47034
S|(Tell Tawil)|36.55597|40.74927
S|(Tell Tawil)|36.66238|40.28371
S|(Tell Tawila)|36.53988|39.49449
S|(Tell Ṭawil Sharqi)|36.56173|40.75433
S|(Tell Tawil Sharqi)|36.65232|40.27021
S|(Tell Tawisen)|33.85556|45.03803
S|(Tell Taya)|36.33258|42.49356
S|(Tell Taya)|36.88797|41.51316
S|(Tell Tayara)|36.20517|37.29592
S|(Tell Tchohash Tahtani)|36.93725|40.79999
S|(Tell Tebilla)|31.05687|31.58145
S|(Tell Tefia)|36.22496|42.73405
S|(Tell Temmi)|36.66805|41.06696
S|(Tell Tendy)|30.85467|49.47171
S|(Tell Thadayain)|35.84850|38.72978
S|(Tell Thameh)|36.49533|43.16658
S|(Tell Tibni)|35.61736|39.81869
S|(Tell Tinnis)|31.20062|32.23555
S|(Tell Tlai)|36.55785|44.32269
S|(Tell Tleïssîyé)|35.36759|36.91959
S|(Tell Tnenir)|36.42025|40.86591
S|(Tell Tokal)|36.61968|39.84758
S|(Tell Torbeyeh)|32.63341|44.24502
S|(Tell Tukhmi)|31.93326|45.05237
S|(Tell Tuqan)|35.82801|36.95843
S|(Tell Turki)|35.59501|42.86848
S|(Tell Turlu / Şehladeh Hüyük)|37.06915|37.75885
S|(Tell Turundah)|36.49438|36.86845
S|(Tell Tuwaym H883)|32.39839|45.69219
S|(Tell Tuwayyil)|36.86671|41.57509
S|(Tell Twagiyyat A106)|32.87658|44.59983
S|(Tell Twaim)|36.36039|42.69647
S|(Tell 'Uja)|35.65877|37.05387
S|(Tell Umdayrat)?|31.69839|45.72917
S|(Tell Umm Amir)|36.17650|42.00899
S|(Tell Umm 'Aqrebe)?|35.71077|41.24326
S|(Tell Umm 'Aqrubba)|35.66166|41.19708
S|(Tell Umm Chalcha)|36.57841|42.07228
S|(Tell Umm el-Ajarib)|31.62115|45.93484
S|(Tell Umm el-'Akarik / Tell el-Khur)|33.45044|43.90277
S|(Tell Umm el-Far)?|32.92004|44.67682
S|(Tell Umm el-Fugas H1096)|32.02658|45.36139
S|(Tell Umm el-Hejol / Abu Khashat)|30.95668|46.25775
S|(Tell Umm el-Juren)|32.58680|35.95682
S|(Tell Umm el-Qanatir)|36.13134|42.71211
S|(Tell Umm Qurhafa)|36.67175|40.30436
S|(Tell Unad Khalil)|36.02261|36.69969
S|(Tell Uqair)|32.78170|44.66460
S|(Tell 'Uqla Fawqani)|36.82725|42.22113
S|(Tell Uskof)|36.59812|43.10414
S|(Tell Ustaih A038)|33.51036|44.21704
S|(Tell Uwaynat)|36.68173|42.39439
S|(Tell Uzunarab)|36.23493|36.30010
S|(Tell Wabla)|31.75551|46.84257
S|(Tell Wadan)|33.45052|44.07905
S|(Tell Wadi Aswad)|36.67445|37.73768
S|(Tell Wajif)|31.73838|47.46069
S|(Tell Waksa)|32.13666|44.48605
S|(Tell Wanna)|32.08870|44.77912
S|(Tell Wardin)|34.04517|36.12240
S|(Tell Yanouh)?|34.10239|35.88419
S|(Tell Yaqoob)|36.15609|43.35976
S|(Tell Yara)|36.44661|43.25313
S|(Tell Yaraoun)|35.34453|36.59981
S|(Tell Yargun)|35.12668|44.24386
S|(Tell Yasti)?|36.55140|37.98652
S|(Tell Yatha 2)?|36.28244|43.36550
S|(Tell Yatha 3)|36.30410|43.36244
S|(Tell Yelkhi)|34.28560|45.00143
S|(Tell Youssef Bey)|36.73853|37.92250
S|(Tell Yusuf)??|33.05727|35.79671
S|(Tell Zaafarana)|34.87887|36.76776
S|(Tell Zabib)|36.76166|41.07358
S|(Tell Zaghan)|36.54933|40.75191
S|(Tell Zaitane)|36.05839|37.01205
S|(Tell Zaja')|31.48922|46.40041
S|(Tell Zajrit)|35.61981|36.35944
S|(Tell Zayn el-Abadîn A248)|32.28395|44.72591
S|(Tell Zaytun)|35.66042|36.63664
S|(Tell Zakaria)|34.89126|36.90916
S|(Tell Zalat)|36.28824|42.83174
S|(Tell Zanatri)|36.56748|41.30507
S|(Tell Zeidan)|35.95133|39.09435
S|(Tell Zichariya U213)|31.57477|45.91956
S|(Tell Zimbeg)|36.31132|42.45457
S|(Tell Zindaq)|36.32472|42.44759
S|(Tell Zira'a)|32.62062|35.65587
S|(Tell Ziwan)|37.05829|41.35587
S|(Tell Ziwik)|36.13250|41.63118
S|(Tell Ziyade)|36.41107|40.84419
S|(Tell Zubeidi)|34.21590|45.03864
S|(Tell Zuhra D641)|33.16682|44.94857
S|(Tell Zuwelen)|30.93379|31.89194
S|(Tel Malḥata / Tell el-Milḥ)|31.21727|35.02586
S|(Tel Maresha)|31.59277|34.89834
S|(Tel Mikhmoret)|32.40137|34.86582
S|(Tel Milḥa)|31.46245|34.77628
S|(Tel Nami)|32.66067|34.92551
S|(Tel Qanah)|32.13254|34.88818
S|(Tel Qashish / Tell Qasis)|32.68508|35.10929
S|(Tel Qedesh)|32.55929|35.21630
S|(Tel Qudadi)|32.10339|34.77692
S|(Tel Regev)|32.75877|35.09020
S|(Tel Rekhesh / Tell Mukharkhash)|32.65330|35.46620
S|(Tel Sa'albim)|31.86963|34.98725
S|(Tel Sera')|31.39118|34.68060
S|(Tel Shamaṭ)|32.61331|35.56407
S|(Tel Shiqmona)|32.82451|34.95564
S|(Tel Shokah)|32.49731|35.45879
S|(Tel Shokan)|32.60524|35.56463
S|(Tel Socoh)|31.68220|34.97437
S|(Tel Taninim)|32.53865|34.90174
S|(Tel Te'omim)|32.44186|35.49430
S|(Tel Tsaf)|32.40674|35.54826
S|(Tel Yaqush)|32.61284|35.55573
S|(Tel Yarmut / Khirbet el-Yarmuk)|31.70846|34.97504
S|(Tel Yizre'el)|32.55693|35.32843
S|(Tel Yodefat)|32.83218|35.27774
S|(Tel Zan)|32.60742|35.55969
S|(Tel Zayit)|31.62915|34.83032
S|(Tel Zeton)|32.09957|34.83697
S|(Tel Zoharah)|32.51250|35.45439
S|(Tepealtı / Tell Ya'qub)|37.09669|41.36991
S|(Tepeüstü / Tell Mimar)|37.11155|41.38515
S|(Teppe Abdulla Khalal)?|35.08553|44.41039
S|(Teppe Ali Shahi)|32.00361|48.80978
S|(Teppe Ama Hosn SRP 113)|34.89998|45.68146
S|(Teppe Anganeh)|37.79372|45.12597
S|(Teppe Askerabad)|37.65306|45.04627
S|(Teppe Baglar)|37.74177|45.07061
S|(Teppe Balajuk)|37.60879|44.96216
S|(Teppe Balu 1)|37.62599|45.02635
S|(Teppe Band-i-bal KS 13)|32.30038|48.23758
S|(Teppe Borašan)|37.57253|45.13977
S|(Teppe Bormi)?|31.24129|49.58903
S|(Teppe Bowla)|32.66544|47.25379
S|(Teppe Chenchi)|36.48211|43.22937
S|(Teppe Čičaklu)|37.62762|45.10676
S|(Teppe Dailaq)|37.63197|45.08870
S|(Teppe Darouqeh)|31.87561|48.88347
S|(Teppe Dinkha)|37.00641|45.16678
S|(Teppe Dizajtakye)|37.42244|45.16970
S|(Teppe Djamshdi)|34.05844|48.12470
S|(Teppe el-Jajis?)|31.82589|48.58482
S|(Teppe Fakhira)|35.23999|43.60688
S|(Teppe Farukhabad)|32.58733|47.22410
S|(Teppe Galeh Bongoon KS 37)|32.24294|48.40208
S|(Teppe Gawra)|36.49582|43.26043
S|(Teppe Giyan)?|34.16072|48.22664
S|(Teppe Goughan)|32.58014|47.33745
S|(Teppe Guijalu)|37.64142|45.15022
S|(Teppe Guran)|33.75656|47.09741
S|(Teppe Gyaur)|37.41427|45.10981
S|(Teppe Hesar)|36.15450|54.38523
S|(Teppe Hajali / Teppe Jamali)|35.25586|44.29437
S|(Teppe Jaffarabad)?|32.27481|48.22420
S|(Teppe Jarabad)|37.22684|44.95517
S|(Teppe Jarčalu)|37.59411|45.14216
S|(Teppe Kalan SRP 18)|34.45383|45.14309
S|(Teppe Kanada)?|35.14750|45.90275
S|(Teppe Kazabad A)?|33.71851|47.07677
S|(Teppe Keihf)?|32.04129|48.27540
S|(Teppe Kočebaš 1)|37.62023|45.14504
S|(Teppe Khaiber)|34.54415|46.64121
S|(Teppe Kočebaš 2)|37.62255|45.14724
S|(Teppe Kordlar)|37.56349|45.21357
S|(Teppe Kushkak)|30.25177|51.49424
S|(Teppe Leban)|36.18955|43.55733
S|(Teppe Leyli)|37.40069|45.16527
S|(Teppe Maidan)|37.75895|45.08263
S|(Teppe Marani)|35.21083|45.92139
S|(Teppe Meshwall 1)|31.77234|48.89890
S|(Teppe Meshwall 2)|31.77854|48.91692
S|(Teppe Miraziz)|37.58346|45.12753
S|(Teppe Mohammed Agha KS 16)|32.30425|48.26434
S|(Teppe Musiyan)|32.55299|47.35102
S|(Teppe Naqara Khan)|35.21529|46.03113
S|(Teppe Nargi)|37.33563|44.92157
S|(Teppe Nazlu 1)|37.67758|44.96512
S|(Teppe Nush-i Jan)|34.36533|48.63299
S|(Teppe Qalehjuk)|37.40839|45.15570
S|(Teppe Qaramanlu 1)|37.66312|45.17964
S|(Teppe Qislašuq)|37.62495|45.05108
S|(Teppe Sabz)|32.63725|47.21959
S|(Teppe Sabz)?|30.64201|50.30271
S|(Teppe Salim)|35.06483|44.38706
S|(Teppe Sanjar KS 113)|32.14371|48.52418
S|(Teppe Sharafabad KS 36)|32.28557|48.36564
S|(Teppe Šarbat)|37.71867|45.15581
S|(Teppe Senjar KS 7)|32.36444|48.20073
S|(Teppe Shaqaridg)|31.77118|48.98510
S|(Teppe Sialk)|33.96851|51.40462
S|(Teppe Sornah)|30.34390|51.29379
S|(Teppe Suleiman KS 24)|32.23929|48.23572
S|(Teppe Taimur)|35.16184|44.28686
S|(Teppe Tellu)|37.49801|44.78776
S|(Teppe Turkman)|37.43815|45.23160
S|(Teppe Twaim KS 112)|32.17576|48.50893
S|(Teppe Yahya)|28.33090|56.86742
S|(Teppe-ye Mosalla)|34.79670|48.52438
S|(Teppe Zeyveh)|37.24566|44.90196
S|(Terba Sipi)|36.96164|40.53412
S|(Tıladir Tepe)|36.86531|38.03736
S|(Tilhalit?)|36.76726|37.63870
S|(Tille)|36.25455|44.75611
S|(Tille Höyük)?|37.75206|38.89239
S|(Tilmen Höyük)|37.03002|36.70420
S|(Timnah)|29.79233|34.93359
S|(Tol-e Ajori)|29.93639|52.85501
S|(Toll-e Bashi)|30.04600|52.68273
S|(Trad)|35.15632|36.97288
S|(Tsitsernakaberd)|40.18762|44.49793
S|(Tsovak)|40.18667|45.62355
S|(Tud)|25.58308|32.53322
S|(Tukh el-Qaramus)|30.68162|31.64100
S|(Tulul Abu Adhem A266)|32.30631|45.02796
S|(Tulul Abu Dan H1101)|32.21807|45.42257
S|(Tulul Abu Fatas H1439)|31.97196|45.67814
S|(Tulul Abu Hadmah)|32.51623|44.48334
S|(Tulul Abu Jawan D682)|33.13265|44.80540
S|(Tulul Abu Qubur D86)|33.70918|44.50671
S|(Tulul Abu Qubur D87)|33.71000|44.49338
S|(Tulul Abu Sa'ir)|32.79068|44.50076
S|(Tulul Abu Yiwalik D397)|33.40040|45.07486
S|(Tulul Ahmad)|32.58462|44.26132
S|(Tulul Ahmar)|33.02412|44.25276
S|(Tulul 'Ain el-Bqara)?|36.21544|43.04235
S|(Tulul 'Ain Nasir)?|36.12312|43.07141
S|(Tulul Bashmanah)|35.91793|43.02489
S|(Tulul Bawi / Tulul Umm el-'Ain D663)|33.11658|44.57099
S|(Tulul Binat el-Rasa)|32.62265|44.26920
S|(Tulul ed-Debah)|36.56098|41.35684
S|(Tulul el-'Afanaljat)|32.88904|44.16259
S|(Tulul el-'Arysh)|36.09357|42.94310
S|(Tulul el-'Awadyat)|31.45314|46.50466
S|(Tulul el-'Awadyat)|31.53706|46.51091
S|(Tulul el-Bag)|35.43169|43.10980
S|(Tulul el-Baqarat TB1)|32.33765|45.72151
S|(Tulul el-Baqarat TB5)|32.33347|45.71768
S|(Tulul el-Baqarat TB7)|32.33138|45.73346
S|(Tulul el-Baqarat TB9)|32.34250|45.70690
S|(Tulul el-Baqarat TB10)|32.34426|45.71595
S|(Tulul el-Far)|33.37811|36.46764
S|(Tulul el-Hibir A006)|33.89606|44.25430
S|(Tulul el-Madain)|31.61936|46.22707
S|(Tulul el-Masihab)|31.06027|46.81690
S|(Tulul el-M'bedi)|36.19045|43.12272
S|(Tulul el-Ramul)|32.93461|44.45666
S|(Tulul es-Sib)|34.19330|45.05793
S|(Tulul eth-Thalathat)|36.41413|42.63311
S|(Tulul ez-Zarki)|31.86433|46.37845
S|(Tulul Faridishad)|33.88858|45.11565
S|(Tulul Hajim)|32.53974|44.14041
S|(Tulul Hajim)|32.53237|44.14090
S|(Tulul Hamediyat)|34.18563|44.99285
S|(Tulul Jerbasi)|30.74883|46.95134
S|(Tulul Jrebi'at)|32.26553|44.69486
S|(Tulul Jrebi'at)|32.25874|44.69542
S|(Tulul Jumali H503-504)|32.49906|44.99677
S|(Tulul Karmisat)|31.84044|46.35426
S|(Tulul Khabari)|34.19200|44.99143
S|(Tulul Khalfat K54)|32.67203|44.67114
S|(Tulul Khalidiya)|32.25034|44.70133
S|(Tulul Khattab D220-223)|33.47412|44.51594
S|(Tulul Khiro Kushad?)|33.56265|45.05467
S|(Tulul Muhsin)|32.98601|44.41211
S|(Tulul Muhsin)|32.96728|44.40707
S|(Tulul Marad el-'Amran)|32.74477|44.23581
S|(Tulul Tubiya)|32.82169|44.40652
S|(Tulul Tuwaymat H635)|32.42568|45.61586
S|(Tulul Sa'id)|32.85578|44.39479
S|(Tulul Ugla)|36.02624|41.61432
S|(Tümp)|36.84722|37.46018
S|(Turan Teppe)|36.97320|54.56194
S|(Tureng Teppe)|36.93824|54.58640
S|(Turluk)|37.00346|38.94241
S|(Turna)|37.32958|39.51400
S|(Tuweirij / Ishan Khalfah K156)|32.46821|44.74531
S|(U177)|31.67442|45.77198
S|(U270)|31.41068|45.60204
S|(U301)|31.37667|45.62185
S|(U453)|31.31402|46.02473
S|(U464)|31.22117|45.99386
S|(U465)|31.20378|46.09189
S|(U466)|31.18857|46.08953
S|(Udhruh)|30.32924|35.59574
S|('Ukbara A017)|33.78060|44.31242
S|(Umm edh-Dhahab)|32.55012|44.60360
S|(Umm el-'Ajjaj)|31.54399|45.87586
S|(Umm el-Anab Tahtani)|36.89504|40.93293
S|(Umm el-Awlad K148)|32.53103|44.66977
S|(Umm el-Fidays)?|35.47022|43.44783
S|(Umm el-Haffriyat / Jezaziyat U039)|31.64127|45.49617
S|(Umm el-Hafriyat)|32.12500|45.47850
S|(Umm el-Jimal)|32.32699|36.36975
S|(Umm el-Khezi H1389)|31.75832|45.37891
S|(Umm el-Wawiya)|31.26130|45.76222
S|(Umm es-Sadaya)|36.67441|37.63319
S|(Umm Jatil)|31.38997|46.57862
S|(Uşaklı Höyük)|39.81307|35.05259
S|('Usiyeh)|34.32578|42.12197
S|(Vahvin)|36.66736|37.36662
S|(Vasılı)|36.81631|37.64963
S|(Wadi Brisa)?|34.43171|36.31152
S|(Wadi Khatkhun)|36.62933|42.86452
S|(Wakis)|32.15716|44.46274
S|(Yananköy)|36.69787|37.27259
S|(Yanik Teppe)|37.98077|46.00295
S|(Yaremjeh)|36.30311|43.17633
S|(Yarim Teppe I)|36.34039|42.35207
S|(Yarim Teppe II)|36.33761|42.34843
S|(Yaşarköy)|37.08546|40.54493
S|(Yasin Teppe)|35.35984|45.64976
S|(Yassi Höyük)|39.99307|34.88257
S|(Yavneh Yam)|31.92499|34.69715
S|(Yazılıkavak)|37.08581|39.08710
S|(Yazılıkaya)|40.02538|34.63286
S|(Yel Baba)|36.60235|37.17489
S|(Yel Khalalat)|32.22846|44.82759
S|(Yeniköy)|36.87597|37.59545
S|(Yesemek)|36.89977|36.74354
S|(Yeşil Hisar)|38.35333|35.08633
S|(Yiftahel / Khalet Khalladyiah)|32.75517|35.22866
S|(Yollarbaşı)|37.31072|39.65723
S|(Yona)|36.79173|37.58802
S|(Yukarı Anzaf)|38.55936|43.47061
S|(Yukarıbeğdeş)|36.84738|38.90450
S|(Yümüktepe Mersin)|36.80127|34.60412
S|(Zabqin)?|33.16622|35.26610
S|(Zage)|35.82317|49.97503
S|(Zaiyad)|35.39951|36.62162
S|(Zakros)|35.09827|26.26137
S|(Zalebiye)|35.66855|39.84233
S|(Zawiyeh)|34.29269|42.17222
S|(Zekah)|35.34015|36.57732
S|(Zeytinli Bahçe Höyük)|36.99573|37.97769
S|(Zeyve Höyük / Porsuk-Ulukışla)|37.51473|34.58111
S|(Zibliyat)|32.28390|45.10974
S|(Ziwiye)|36.27379|46.68875
N|NIRAQ|36.33390|42.83164
N|NIRAQ|35.34100|45.79002
N|NIRAQ|35.66068|44.28652
N|NIRAQ|35.66223|44.31740
N|NIRAQ|35.68549|44.25741
N|NIRAQ|35.67631|44.25741
N|NIRAQ|35.64132|44.31684
N|NIRAQ?|36.35677|42.83086
N|NIRAQ|36.16998|42.67366
N|NIRAQ|36.35586|42.78838
N|NIRAQ|35.90359|42.88350
N|NIRAQ|35.97769|42.86821
N|NIRAQ?|36.37815|42.72907
N|NIRAQ|36.11715|42.88756
N|NIRAQ?|36.21535|42.83234
N|NIRAQ|36.36602|42.81012
N|NIRAQ|36.39363|42.75284
N|NIRAQ|35.34793|45.79159
N|NIRAQ|35.26178|45.89190
N|NIRAQ|35.33918|45.89151
N|NIRAQ|35.31164|45.82389
N|NIRAQ|35.30408|45.83302
N|NIRAQ|35.29968|45.85020
N|NIRAQ|35.26204|45.88518
N|NIRAQ|35.27112|45.90894
N|NIRAQ|35.29304|45.84754
N|NIRAQ|35.32008|45.83490
N|NIRAQ|35.30251|46.02234
N|NIRAQ|35.29852|45.83636
N|NIRAQ|35.31725|45.84896
N|NIRAQ|35.32452|45.83261
N|NIRAQ|35.34192|45.83899
N|NIRAQ|35.30178|45.99102
N|NIRAQ|35.29908|45.83533
N|NIRAQ|35.29612|45.85813
N|NIRAQ|35.29664|45.98185
N|NIRAQ|35.29856|45.77076
N|NIRAQ|35.30353|45.97011
N|NIRAQ|35.27039|45.86925
N|NIRAQ|35.27139|45.81376
N|NIRAQ|35.29623|45.82695
N|NIRAQ|35.23671|45.88295
N|NIRAQ|35.24782|45.87364
N|NIRAQ|36.93303|42.35916
N|NIRAQ|35.25372|45.89064
N|NIRAQ|36.40035|43.04534
N|NIRAQ|37.12643|42.43675
N|NIRAQ|34.32779|44.54260
N|NIRAQ|35.52865|45.33913
N|NIRAQ|34.20433|44.23941
N|NIRAQ|33.82475|44.50804
N|NIRAQ|34.27297|44.39223
N|NIRAQ|34.23482|44.31190
N|NIRAQ|35.28270|45.94829
N|NIRAQ|34.26650|44.38394
N|NIRAQ|34.19521|44.11313
N|NIRAQ|35.00001|44.40303
N|NIRAQ|34.22375|44.32905
N|NIRAQ|35.50372|44.25650
N|NIRAQ|36.70327|41.97572
N|NIRAQ|35.29636|45.87807
N|NIRAQ|35.51196|44.22857
N|NIRAQ|36.49126|43.21508
N|NIRAQ|35.29897|45.88355
N|NIRAQ|36.01251|43.37988
N|NIRAQ|36.05126|43.36353
N|NIRAQ|36.11692|43.39085
N|NIRAQ|35.23708|43.81278
N|NIRAQ|35.58704|43.94865
N|NIRAQ|35.34082|44.07235
N|NIRAQ|35.21634|43.84947
N|NIRAQ|35.17965|43.79040
N|NIRAQ|35.08594|43.87014
N|NIRAQ|35.13267|43.66453
N|NIRAQ|35.39996|44.06175
N|NIRAQ|36.04422|43.88669
N|NIRAQ|35.38011|43.81105
N|NIRAQ|36.33693|42.44923
N|NIRAQ|35.24206|44.61145
N|NIRAQ|35.28291|43.85460
N|NIRAQ|36.31684|42.42779
N|NIRAQ|35.34130|43.76111
N|NIRAQ|35.28282|43.76012
N|NIRAQ|35.19403|43.75492
N|NIRAQ|35.31359|43.92810
N|NIRAQ|35.26858|43.87653
N|NIRAQ|35.43223|43.85551
N|NIRAQ|37.08719|42.42671
N|NIRAQ|36.28351|42.10484
N|NIRAQ|35.70005|44.23584
N|NIRAQ|35.28791|45.85626
N|NIRAQ|35.30159|45.92748
N|NIRAQ|36.97871|42.43777
N|NIRAQ|35.96942|44.04429
N|NIRAQ|35.28541|45.88726
N|NIRAQ|35.28093|45.98776
N|NIRAQ|36.01986|43.81087
N|NIRAQ|35.28936|45.91071
N|NIRAQ|35.32895|45.86642
N|NIRAQ|36.04272|43.90500
N|NIRAQ|35.97435|43.94774
N|NIRAQ|35.35630|45.94634
N|NIRAQ|35.32974|45.95573
N|NIRAQ|35.46477|45.47303
N|NIRAQ|36.12704|43.56729
N|NIRAQ|36.04667|43.93973
N|NIRAQ|36.23010|44.05070
N|NIRAQ|36.03125|43.84529
N|NIRAQ|36.06828|43.96475
N|NIRAQ|36.03922|43.86214
N|NIRAQ|36.18309|44.85762
N|NIRAQ|36.19381|44.88902
N|NIRAQ|34.71414|43.69655
N|SIRAQ|32.45721|44.41652
N|SIRAQ|32.64652|44.27480
N|SIRAQ|32.69000|44.29832
N|SIRAQ|32.76440|44.57339
N|SIRAQ|32.64086|44.31221
N|SIRAQ|32.67142|44.29357
N|SIRAQ|31.95621|44.53514
N|SIRAQ|32.64133|44.31290
N|SIRAQ|32.78470|44.36904
N|SIRAQ|32.63486|44.37471
N|SIRAQ|32.86611|44.36951
N|SIRAQ|32.74501|44.40442
N|SIRAQ|32.83831|44.38049
N|SIRAQ|32.72587|44.43924
N|SIRAQ|32.77029|44.39706
N|SIRAQ|32.67418|44.41685
N|SIRAQ|32.90647|44.38692
N|SIRAQ|32.67169|44.38926
N|SIRAQ|32.77494|44.23332
N|SIRAQ|32.68731|44.38718
N|SIRAQ|32.48521|44.63723
N|SIRAQ|32.59424|44.42767
N|SIRAQ|32.93961|44.37152
N|SIRAQ|32.74730|44.40032
N|SIRAQ|32.93497|44.36473
N|SIRAQ|32.57243|44.34602
N|SIRAQ|32.58014|44.36486
N|SIRAQ|32.93921|44.17031
N|SIRAQ|32.85911|44.30031
N|SIRAQ|32.93197|44.20269
N|SIRAQ|32.80131|44.32867
N|SIRAQ|31.70273|46.03767
N|SIRAQ|32.92986|44.22123
N|SIRAQ|31.77502|45.99656
N|SIRAQ|31.69361|46.08707
N|SIRAQ|31.77434|45.99118
N|SIRAQ|32.08286|44.76614
N|SIRAQ|31.65449|45.94615
N|SIRAQ|31.92332|45.90489
N|SIRAQ|31.68429|46.06527
N|SIRAQ|31.92135|45.92870
N|SIRAQ|31.73377|45.85295
N|SIRAQ|31.70235|45.84804
N|SIRAQ|31.75262|45.86510
N|SIRAQ|31.81485|45.85353
N|SIRAQ|31.77961|45.85495
N|SIRAQ|31.88185|45.86019
N|SIRAQ|31.86786|45.84590
N|SIRAQ|31.54627|46.04756
N|SIRAQ|31.88976|45.85379
N|SIRAQ|31.82357|46.06036
N|SIRAQ|31.67411|46.05838
N|SIRAQ|31.89072|45.84129
N|SIRAQ|32.40589|44.40102
N|SIRAQ|31.91795|45.92328
N|SIRAQ|32.42302|44.40156
N|SIRAQ|32.51042|44.37972
N|SIRAQ|32.07552|44.77626
N|SIRAQ|32.63093|44.40545
N|SIRAQ|31.23944|46.49791
N|SIRAQ|31.15769|46.11653
N|SIRAQ|32.87262|44.40786
N|SIRAQ|32.71175|44.42353
N|SIRAQ|32.20474|44.62454
N|SIRAQ|31.21689|46.02250
N|SIRAQ|32.90955|44.26517
N|SIRAQ|32.95953|44.51579
N|SIRAQ|31.19849|45.91485
N|SIRAQ|32.89843|44.50438
N|SIRAQ|32.98107|44.54391
N|SIRAQ|32.97571|44.55029
N|SIRAQ|33.62602|44.45815
N|SIRAQ|32.99075|44.51705
N|SIRAQ|31.80492|45.94166
N|SIRAQ|31.14665|46.19292
N|SIRAQ|32.92688|44.53161
N|SIRAQ|32.98958|44.30997
N|SIRAQ|32.67258|44.39244
N|SIRAQ|32.88885|44.32657
N|SIRAQ|31.23752|45.79175
N|SIRAQ|32.97712|44.54048
N|SIRAQ|32.22215|46.24124
N|SIRAQ|32.88920|44.38662
N|SIRAQ|32.86852|44.49742
N|SIRAQ|32.98901|44.29957
N|SIRAQ|32.78693|44.38844
N|SIRAQ|32.91972|44.49936
N|SIRAQ|32.83744|44.44379
N|SIRAQ|32.76886|44.53684
N|SIRAQ|32.85868|44.34839
N|SIRAQ|32.77851|44.34596
N|SIRAQ|32.69576|44.42579
N|SIRAQ|32.67230|44.44093
N|SIRAQ|32.95403|44.46310
N|SIRAQ|32.86919|44.52792
N|SIRAQ|32.92663|44.54378
N|SIRAQ|32.89592|44.29805
N|SIRAQ|32.84817|44.52860
N|SIRAQ|32.72039|44.32420
N|SIRAQ|32.67066|44.41067
N|SIRAQ|32.68591|44.42165
N|SIRAQ|32.65048|44.39223
N|SIRAQ|32.81922|44.46410
N|SIRAQ|32.82491|44.39220
N|SIRAQ|32.62354|44.27624
N|SIRAQ|32.63053|44.41146
N|SIRAQ|32.63494|44.24756
N|SIRAQ|32.61840|44.24189
N|SIRAQ|32.96430|44.32977
N|SIRAQ|32.71432|44.32730
N|SIRAQ|32.56034|44.36032
N|SIRAQ|33.02894|44.35814
N|SIRAQ|32.60182|44.30636
N|SIRAQ|32.56782|44.32344
N|SIRAQ|32.55948|44.29678
N|SIRAQ|32.55772|44.28852
N|SIRAQ|31.81356|44.44730
N|SIRAQ|32.03322|44.50736
N|SIRAQ|32.70061|44.28808
N|SIRAQ|32.75465|44.34837
N|SIRAQ|32.90453|44.28391
N|SIRAQ|32.87149|44.45453
N|SIRAQ|32.62554|44.31517
N|SIRAQ|32.84223|44.44641
N|SIRAQ|32.82045|44.45237
N|SIRAQ|32.59737|44.29524
N|SIRAQ|32.92557|44.42663
N|SIRAQ|31.84638|45.96568
N|SIRAQ|32.07910|45.96526
N|SIRAQ|32.55009|44.35987
N|SIRAQ|32.93668|44.36382
N|SIRAQ|32.51698|44.34358
N|SIRAQ|32.61879|44.29751
N|SIRAQ|32.59123|44.27888
N|SIRAQ|32.64949|44.28125
N|SIRAQ|32.53000|44.28171
N|SIRAQ|32.87416|44.98810
N|SIRAQ|32.49501|44.38010
N|SIRAQ|31.72208|46.63684
N|SIRAQ|31.34335|46.46588
N|SIRAQ|32.57382|44.35251
N|SIRAQ|31.63373|45.85714
N|SIRAQ|32.36742|45.76663
N|SIRAQ|32.35267|45.93069
N|SIRAQ|32.36662|45.76223
N|SIRAQ|31.63589|45.86845
N|SIRAQ|31.62682|45.87435
N|SIRAQ|32.45041|45.95614
N|SIRAQ|32.13855|45.82475
N|SIRAQ|32.26975|45.72086
N|SIRAQ|32.28382|45.71034
N|SIRAQ|32.44791|45.93087
N|SIRAQ|32.29122|45.64973
N|SIRAQ|32.36462|45.76360
N|SIRAQ|32.09933|44.85963
N|SIRAQ|32.24962|44.42659
N|SIRAQ|32.31917|44.50165
N|SIRAQ|32.13357|44.85296
N|SIRAQ|31.68286|46.49246
N|SIRAQ|31.62188|46.55393
N|SIRAQ|32.21177|44.44181
N|SIRAQ|32.74769|44.48900
N|SIRAQ|32.76762|44.48321
N|SIRAQ|32.78422|44.42743
N|SIRAQ|33.22516|44.09399
N|SIRAQ|32.39239|45.48626
N|SIRAQ|32.47920|44.72409
N|SIRAQ|32.45006|44.86370
N|SIRAQ|31.26556|45.76527
N|SIRAQ|31.88688|46.37100
N|SIRAQ|33.06832|44.45418
N|SIRAQ|33.43889|44.05283
N|SIRAQ|32.42510|45.41207
N|SIRAQ|32.48821|45.50135
N|SIRAQ|32.09536|45.92938
N|SIRAQ|32.45535|45.47131
N|SIRAQ|32.42634|45.04131
N|SIRAQ|32.43302|45.35218
N|SIRAQ|32.38272|45.52726
N|SIRAQ|32.37655|45.52402
N|SIRAQ|32.40866|45.84729
N|SIRAQ|32.33148|45.59680
N|SIRAQ|32.65505|44.53683
N|SIRAQ|31.51830|46.51180
N|SIRAQ|32.29758|45.50418
N|SIRAQ|32.31661|44.55140
N|SIRAQ|32.77512|44.90223
N|SIRAQ|32.25461|44.71634
N|SIRAQ|31.48019|46.51893
N|SIRAQ|31.48310|46.52320
N|SIRAQ|31.54510|46.50881
N|SIRAQ|31.91715|46.37208
N|SIRAQ|32.45254|46.06034
N|SIRAQ|32.70260|44.58438
N|SIRAQ|32.75195|44.52610
N|SIRAQ|34.02206|42.51525
N|SIRAQ|33.97844|42.55653
N|SIRAQ|33.87356|42.73258
N|SIRAQ|33.51576|42.96225
N|SIRAQ|32.80340|44.82630
N|SIRAQ|32.86392|44.30057
N|SIRAQ|32.89798|44.67642
N|SIRAQ|32.48075|44.31895
N|SIRAQ|32.54074|44.47644
N|SIRAQ|32.67079|44.89507
N|SIRAQ|33.44045|44.22832
N|SIRAQ|32.47591|44.78404
N|SIRAQ|33.19764|44.16764
N|SIRAQ|32.78812|44.91835
N|SIRAQ|32.65821|44.38159
N|SIRAQ|32.78319|44.93821
N|SIRAQ|32.88981|44.65025
N|SIRAQ|32.52437|44.92565
N|SIRAQ|32.91687|44.71132
N|SIRAQ|32.56744|44.94370
N|SIRAQ|32.20733|45.73769
N|SIRAQ|31.97101|45.34280
N|SIRAQ|32.43820|44.29130
N|SIRAQ|32.75829|44.22705
N|SIRAQ|32.59545|44.09577
N|SIRAQ|32.70990|44.77690
N|SIRAQ|32.61395|44.09182
N|SIRAQ|32.68936|44.61989
N|SIRAQ|32.59946|44.10575
N|SIRAQ|32.69527|44.04373
N|SIRAQ|32.66776|44.02904
N|SIRAQ|32.73974|44.23514
N|SIRAQ|32.75685|44.18861
N|SIRAQ|32.76068|44.16558
N|SIRAQ|32.75541|44.17637
N|SIRAQ|32.75894|44.21583
N|SIRAQ|32.65944|44.03433
N|SIRAQ|32.65064|43.98464
N|SIRAQ|33.68149|44.58534
N|SIRAQ|33.59123|44.59350
N|SIRAQ|33.10133|44.09667
N|SIRAQ|33.67551|44.57851
N|SIRAQ|32.61232|44.96743
N|SIRAQ|32.86124|44.70728
N|SIRAQ|32.57385|45.09572
N|SIRAQ|32.88466|44.88107
N|SIRAQ|33.20039|44.23976
N|SIRAQ|32.88696|44.84775
N|SIRAQ|32.15337|46.55657
N|SIRAQ|32.13746|46.63873
N|SIRAQ|32.11705|46.31316
N|SIRAQ|32.28370|46.34203
N|SIRAQ|32.34692|46.32364
N|SIRAQ|32.01647|46.57036
N|SIRAQ|31.93771|46.55147
N|SIRAQ|31.79659|46.02570
N|SIRAQ|31.93562|46.18495
N|SIRAQ|31.13503|46.36092
N|SIRAQ|31.32062|46.81738
N|SIRAQ|32.42029|46.32916
N|SIRAQ|32.37318|46.29601
N|SIRAQ|31.96923|46.51866
N|SIRAQ|33.59524|44.73026
N|SIRAQ|33.22708|44.66348
N|SIRAQ|32.67118|44.71991
N|SIRAQ|32.60036|44.69360
N|SIRAQ|32.66797|44.66444
N|SIRAQ|31.69110|47.27166
N|SIRAQ|32.51750|44.41650
N|SIRAQ|32.39549|44.32957
N|SIRAQ|32.50963|44.40198
N|SIRAQ|32.46377|44.41912
N|SIRAQ|32.45477|44.41339
N|SIRAQ|32.55295|44.48145
N|SIRAQ|32.84162|44.45381
N|SIRAQ|32.48383|44.73370
N|SIRAQ|33.07622|44.15821
N|SIRAQ|32.57456|44.37226
N|SIRAQ|32.69314|44.37332
N|SIRAQ|32.96313|44.34840
N|SIRAQ|33.06434|44.17817
N|SIRAQ|33.04191|44.25373
N|SIRAQ|33.05597|44.18223
N|SIRAQ|32.94583|44.38484
N|SIRAQ|32.51726|44.40744
N|SIRAQ|33.02326|44.33181
N|SIRAQ|33.07158|44.15319
N|SIRAQ|33.02799|44.23497
N|SIRAQ|33.02700|44.32061
N|SIRAQ|33.05276|44.19133
N|SIRAQ|33.16847|44.13640
N|SIRAQ|33.02522|44.36001
N|SIRAQ|33.07554|44.16257
N|SIRAQ|32.75350|44.39913
N|SIRAQ|33.06224|44.16863
N|SIRAQ|33.03169|44.22634
N|SIRAQ|33.22735|44.07659
N|SIRAQ|32.75397|44.40653
N|SIRAQ|33.05121|44.18429
N|SIRAQ|33.22676|44.01617
N|SIRAQ|32.74258|44.33937
N|SIRAQ|33.23320|44.06905
N|SIRAQ|33.23353|44.00787
N|SIRAQ|33.03157|44.24587
N|SIRAQ|33.02599|44.35660
N|SIRAQ|33.25152|44.03645
N|SIRAQ|33.02984|44.38033
N|SIRAQ|33.22574|44.04665
N|SIRAQ|32.74907|44.40416
N|SIRAQ|33.22809|44.09394
N|SIRAQ|33.05673|44.11401
N|SIRAQ|33.22393|44.09981
N|SIRAQ|33.22015|44.10475
N|SIRAQ|33.20940|44.11422
N|SIRAQ|33.20482|44.12609
N|SIRAQ|33.20832|44.14145
N|SIRAQ|33.21626|44.19946
N|SIRAQ|33.17785|44.37356
N|SIRAQ|33.02520|44.39186
N|SIRAQ|33.03516|44.39360
N|SIRAQ|32.62877|44.38815
N|SIRAQ|33.21891|44.21748
N|SIRAQ|33.06481|44.17146
N|SIRAQ|32.57620|44.42331
N|SIRAQ|32.60170|44.41063
N|SIRAQ|32.56826|44.40214
N|SIRAQ|32.64462|44.39772
N|SIRAQ|32.77286|44.41546
N|SIRAQ|33.08860|44.46723
N|SIRAQ|33.08475|44.49135
N|SIRAQ|32.50751|44.70022
N|SIRAQ|32.50980|44.70217
N|SIRAQ|32.51335|44.68894
N|SIRAQ|32.86859|44.40441
N|SIRAQ|33.24527|43.86679
N|SIRAQ|32.65333|44.74766
N|SIRAQ|32.63450|44.76603
N|SIRAQ|32.87981|44.16533
N|SIRAQ|32.96050|44.20047
N|SIRAQ|32.80075|44.48832
N|SIRAQ|32.86811|44.29584
N|SIRAQ|32.88422|44.31755
N|SIRAQ|32.91060|44.46138
N|SIRAQ|32.88875|44.46939
N|SIRAQ|32.90023|44.44888
N|SIRAQ|32.75781|44.40370
N|SIRAQ|32.91274|44.23660
N|SIRAQ|32.87223|44.47058
N|SIRAQ|32.91460|44.43963
N|SIRAQ|32.86782|44.46066
N|SIRAQ|32.70228|44.56941
N|SIRAQ|32.90343|44.55233
N|SIRAQ|32.64562|44.73437
N|SIRAQ|32.71004|44.70628
N|SIRAQ|32.77037|44.50695
N|SIRAQ|32.74737|44.51749
N|SIRAQ|32.75243|44.53354
N|SIRAQ|32.71799|44.67818
N|SIRAQ|32.65416|44.68419
N|SIRAQ|33.09481|44.38701
N|SIRAQ|33.09451|44.39046
N|SIRAQ|33.09929|44.38376
N|SIRAQ|33.10236|44.37945
N|SIRAQ|33.10266|44.36443
N|SIRAQ|33.10990|44.36102
N|SIRAQ|33.11258|44.32260
N|SIRAQ|33.12448|44.33464
N|SIRAQ|33.13608|44.33317
N|SIRAQ|33.13229|44.39134
N|SIRAQ|33.12613|44.38550
N|SIRAQ|33.13509|44.39236
N|SIRAQ|33.12222|44.41651
N|SIRAQ|33.09255|44.46774
N|SIRAQ|33.09812|44.45986
N|SIRAQ|33.08044|44.48123
N|SIRAQ|33.08289|44.48759
N|SIRAQ|33.04973|44.54334
N|SIRAQ|33.03691|44.54178
N|SIRAQ|32.95930|44.37802
N|SIRAQ|32.93425|44.46279
N|SIRAQ|33.09349|44.38553
N|SIRAQ|32.92832|44.48755
N|SIRAQ|33.00323|44.48256
N|SIRAQ|33.02908|44.44865
N|SIRAQ|33.01616|44.49124
N|SIRAQ|32.93574|44.50651
N|SIRAQ|32.93523|44.50231
N|SIRAQ|32.94190|44.69286
N|SIRAQ|32.92360|44.48875
N|SIRAQ|32.92161|44.48317
N|SIRAQ|33.17222|44.10320
N|SIRAQ|33.16144|44.15014
N|SIRAQ|33.10287|44.21090
N|SIRAQ|33.10229|44.19341
N|SIRAQ|32.76887|44.40046
N|SIRAQ|32.61246|45.34715
N|SIRAQ|32.50573|44.40124
N|SIRAQ|32.50648|44.40662
N|SIRAQ|32.41060|44.89621
N|SIRAQ|32.18715|44.84061
N|SIRAQ|32.40077|44.89146
N|SIRAQ|32.54222|44.48461
N|SIRAQ|32.54152|44.47319
N|SIRAQ|32.54039|44.46557
N|SIRAQ|32.57899|44.34031
N|SIRAQ|32.54389|44.48320
N|SIRAQ|33.40689|43.78932
N|SIRAQ|33.42281|43.67237
N|SIRAQ|33.21801|44.68170
N|SIRAQ|32.60169|44.97326
N|SIRAQ|32.55919|44.30885
N|SIRAQ|32.72596|45.04618
N|SIRAQ|32.74056|45.05382
N|SIRAQ|32.73553|45.03224
N|SIRAQ|32.74231|45.03934
N|SIRAQ|32.74030|45.03193
N|SIRAQ|32.73506|45.04080
N|SIRAQ|32.73963|45.04837
N|SIRAQ|32.74231|45.06022
N|SIRAQ|33.71827|44.84646
N|SIRAQ|33.23596|43.85783
N|SIRAQ|33.23059|43.87387
N|SIRAQ|33.17995|43.96166
N|SIRAQ|33.22651|43.91873
N|SIRAQ|33.22741|43.87977
N|SIRAQ|33.23598|43.86347
N|SIRAQ|32.54375|44.40310
N|SIRAQ|32.75542|44.34200
N|SIRAQ|33.21019|44.11141
N|SIRAQ|31.56961|46.24755
N|SIRAQ|31.58417|46.20094
N|SIRAQ|32.76930|44.65590
N|SIRAQ|32.77156|44.65340
N|SIRAQ|32.77197|44.65035
N|SIRAQ|31.34559|47.01401
N|SIRAQ|32.77227|44.65935
N|SIRAQ|32.50092|44.50186
N|NSYR|36.75108|38.07389
N|NSYR|36.01173|36.56572
N|NSYR|35.80107|36.98163
N|NSYR|35.46835|36.56282
N|NSYR|35.20102|36.82874
N|NSYR|35.07179|37.03693
N|NSYR|35.04588|36.59357
N|NSYR|34.89541|36.83130
N|NSYR|35.09183|36.81208
N|NSYR|36.05540|37.54489
N|NSYR|36.90684|40.23563
N|NSYR|36.75219|41.02935
N|NSYR|34.97281|36.84273
N|NSYR|35.44329|37.13660
N|NSYR|36.60625|40.38569
N|NSYR|36.48903|40.32422
N|NSYR|36.72738|40.16225
N|NSYR|36.76057|40.08659
N|NSYR|36.90543|40.66287
N|NSYR|36.76451|41.12097
N|NSYR|36.66888|41.33621
N|NSYR|35.26414|37.04762
N|NSYR|37.16316|42.31669
N|NSYR|36.70112|38.94115
N|NSYR|36.69783|38.92940
N|NSYR|36.08278|39.06328
N|NSYR|35.28054|37.12965
N|NSYR|36.01842|39.07826
N|NSYR|36.05635|39.08558
N|NSYR|35.99440|39.09145
N|NSYR|36.91465|41.17029
N|NSYR|36.65509|40.35367
N|NSYR|36.66050|38.99257
N|NSYR|35.32263|40.55820
N|NSYR|36.13550|36.38535
N|NSYR|36.44071|37.47451
N|NSYR|36.66817|37.52017
N|NSYR|36.62319|37.48983
N|NSYR|36.89341|38.36876
N|NSYR|36.60932|38.90109
N|NSYR|36.66856|38.85824
N|NSYR|36.46404|38.95822
N|NSYR|36.45052|38.96417
N|NSYR|36.20845|38.94146
N|NSYR|36.44631|38.96876
N|NSYR|36.00237|39.08865
N|NSYR|36.26453|38.99732
N|NSYR|36.26780|38.99623
N|NSYR|36.27186|38.98507
N|NSYR|36.55345|39.03771
N|NSYR|36.46080|38.94648
N|NSYR|36.62031|38.99856
N|NSYR|36.70316|38.97792
N|NSYR|36.63219|38.99477
N|NSYR|36.69230|39.49197
N|NWSYR|36.72580|36.98922
N|NWSYR|36.54140|36.86043
N|WSYR|34.68337|36.30514
N|WSYR|34.51841|36.47136
N|WSYR|34.97637|35.88475
N|WSYR|34.78926|35.94953
N|SSYR|33.48479|36.57144
N|NJOR|32.52518|35.87282
N|NLIB|34.42490|35.88387
N|ELIB|34.06549|36.11702
N|ELIB|34.07478|36.13819
N|WLIB|33.32802|35.25642
N|STYR|36.69110|37.14098
N|STYR|36.81476|36.54185
N|STYR|36.56500|36.52106
N|STYR|36.44127|36.39351
N|STYR|36.28675|36.68183
N|STYR|36.96569|39.12185
N|STYR|37.81029|40.39835
N|STYR|37.84016|40.29045
N|STYR|38.02805|40.24415
N|STYR|37.13583|42.35377
N|STYR|37.37955|36.89416
N|STYR|37.05846|36.70230
N|STYR|37.18670|36.89143
N|STYR|37.07877|36.74519
N|STYR|37.04586|38.94092
N|STYR|36.82816|37.89382
N|STYR|36.82101|37.84707
N|STYR|36.81056|37.75703
N|STYR|38.37097|38.36385
N|STYR|38.11473|39.86396
N|STYR|37.14958|41.73770
N|STYR|36.89875|38.53093
N|STYR|36.91746|38.49740
N|STYR|36.94021|38.50704
N|STYR|36.70671|38.83277
N|STYR|37.12338|39.06565
N|STYR|37.19057|40.50737
N|STYR|37.22990|39.89100
N|STYR|37.38904|39.56995
N|STYR|37.16763|40.24230
N|STYR|38.04633|39.86669
N|STYR|37.42566|39.55321
N|STYR|37.15350|40.94645
N|STYR|37.15117|41.63825
N|STYR|38.02857|40.20805
N|STYR|38.02388|40.22956
N|STYR|38.02825|40.24420
N|STYR|38.10719|40.22981
N|STYR|38.07426|40.24364
N|STYR|37.84052|40.29044
N|STYR|38.03163|40.14174
N|STYR|38.07199|40.15526
N|STYR|37.11076|41.07458
N|STYR|36.06984|36.37726
N|STYR|36.37176|36.59043
N|STYR|36.78701|39.02530
N|STYR|36.81393|39.02366
N|STYR|36.77776|39.02828
N|TYR|37.63950|34.09571
N|WIRAN|31.76656|48.80236
N|WIRAN|34.43874|48.05924
N|WIRAN|34.54762|48.07954
N|WIRAN|34.54228|48.07365
N|WIRAN|34.47784|48.05952
N|WIRAN|34.49964|48.06750
N|WIRAN|34.50765|48.05930
N|WIRAN|30.65056|50.23947
N|WIRAN|32.18519|48.48590
N|WIRAN|32.18568|48.57962
N|WIRAN|31.82280|48.57489
N|WIRAN|31.93906|48.43433
N|WIRAN|32.13589|48.43880
N|WIRAN|32.18862|48.52173
N|WIRAN|32.22735|48.32631
N|WIRAN|32.28962|48.21704
N|WIRAN|32.15911|48.43833
N|WIRAN|32.19760|48.45531
N|WIRAN|32.24866|48.54996
N|WIRAN|32.15990|48.44294
N|WIRAN|32.13558|48.65983
N|WIRAN|32.19209|48.45772
N|WIRAN|32.13940|48.43619
N|WIRAN|32.14990|48.44985
N|WIRAN|32.04181|48.60131
N|WIRAN|31.80545|48.59628
N|WIRAN|37.01000|46.03474
N|WIRAQ|36.92219|46.06105
N|WIRAN|37.13832|46.04069
N|WIRAN|37.08605|45.96411
N|WIRAN|37.12181|45.91181
N|WIRAN|36.95546|45.38804
N|WIRAN|38.16312|44.65500
N|WIRAN|36.95316|45.52435
N|WIRAN|36.98655|45.30758
N|WIRAN|37.04759|46.01638
N|WIRAN|37.07592|46.06316
N|WIRAN|38.89433|44.98105
N|WIRAN|35.81651|49.95221
N|IRAN|29.85490|52.93928
N|IRAN|29.86665|52.94090
N|NEGYP|31.36897|31.84553
N|NEGYP|30.85965|31.82865
N|NEGYP|30.89328|31.78949
N|NEGYP|30.65332|31.73471
N|NEGYP|30.64855|31.76130
N|NEGYP|30.88189|31.46210
N|NEGYP|30.70333|32.07093
N|NEGYP|30.94168|29.97761
N|NEGYP|31.26861|30.82565
N|NEGYP|30.91104|30.29046
N|NEGYP|30.90728|32.02191
N|NEGYP|30.82062|31.79950
N|NEGYP|30.82935|31.77751
N|NEGYP|30.82208|31.71590
N|NEGYP|31.20634|30.32391
N|NEGYP|31.30874|30.81640
N|NEGYP|31.37265|30.81178
N|NEGYP|31.31090|30.33923
N|SIRAQ|32.88768|44.62049
N|SIRAQ|32.87882|44.62003
N|SIRAQ|30.80886|46.52976
N|SIRAQ|32.71105|44.47186
N|SIRAQ|31.87522|44.39596
N|SIRAQ|32.64060|45.03516
N|SIRAQ|31.76872|44.41876
N|SIRAQ|32.64351|45.03314
N|SIRAQ|31.86909|44.38992
N|SIRAQ|32.60486|45.05991
N|SIRAQ|31.37260|45.06779
N|SIRAQ|32.64383|45.02917
N|SIRAQ|32.78095|44.21154
N|SIRAQ|31.76245|44.42621
N|SIRAQ|31.16645|45.36123
N|SIRAQ|31.13847|45.49399
N|SIRAQ|32.65001|45.02646
N|SIRAQ|32.96096|44.44793
N|SIRAQ|32.95079|44.43943
N|SIRAQ|31.27414|46.55836
N|SIRAQ|30.84300|46.68179
N|SIRAQ|30.79069|46.64770
N|SIRAQ|30.77571|46.70283
N|SIRAQ|30.78166|46.75615
"""

EXTENTS = """\
Anšan|30.01673,52.40936;30.01509,52.40676;30.01401,52.40571;30.01264,52.40517;30.01141,52.40484;30.01029,52.40453;30.00960,52.40436;30.00859,52.40515;30.00796,52.40583;30.00736,52.40682;30.00637,52.40833;30.00559,52.41020;30.00554,52.41201;30.00640,52.41457;30.00820,52.41701;30.00999,52.41900;30.01349,52.42116;30.01534,52.41923;30.01692,52.41728;30.01877,52.41306;30.01673,52.40936
Aššur|35.46147,43.26332;35.46160,43.26323;35.46170,43.26302;35.46163,43.26277;35.46143,43.26248;35.46090,43.26200;35.46032,43.26129;35.46031,43.26128;35.45991,43.26027;35.45936,43.25893;35.45920,43.25752;35.45936,43.25642;35.45897,43.25596;35.45931,43.25539;35.45822,43.25457;35.45735,43.25462;35.45726,43.25471;35.45619,43.25513;35.45519,43.25645;35.45398,43.25934;35.45360,43.26174;35.45311,43.26261;35.45080,43.26322;35.45055,43.26342;35.44971,43.26531;35.44881,43.26703;35.45147,43.26664;35.45359,43.26611;35.45538,43.26536;35.45760,43.26417;35.45852,43.26368;35.45956,43.26349;35.46049,43.26344;35.46131,43.26341;35.46147,43.26332
Babylon|32.53044,44.43705;32.53838,44.45320;32.56228,44.42711;32.56726,44.42642;32.56724,44.42256;32.55725,44.42288;32.55108,44.42110;32.54396,44.41774;32.54074,44.41835;32.53738,44.40664;32.52468,44.41204;32.52800,44.42329;32.52540,44.42539;32.53044,44.43705
Dur-Katlimmu|35.64309,40.73898;35.64204,40.73960;35.64062,40.74293;35.64537,40.74537;35.64893,40.74827;35.64974,40.74613;35.65055,40.74405;35.64464,40.73994;35.64420,40.73952;35.64377,40.73911;35.64309,40.73898
Dur-Šarrukin|36.51441,43.23176;36.51106,43.22885;36.51173,43.22728;36.50966,43.22581;36.50875,43.22718;36.50095,43.22098;36.49234,43.23847;36.50487,43.24874;36.51441,43.23176
Girsu|31.57410,46.17268;31.57238,46.17122;31.57236,46.17116;31.57056,46.17056;31.56626,46.16938;31.56208,46.16856;31.55739,46.16855;31.55323,46.17115;31.54994,46.17462;31.54789,46.17701;31.54764,46.17768;31.54955,46.17936;31.54962,46.17945;31.54967,46.17956;31.54974,46.17964;31.55166,46.18291;31.55361,46.18743;31.55611,46.18865;31.55901,46.18826;31.55903,46.18826;31.56307,46.18635;31.56622,46.18255;31.57169,46.17888;31.57496,46.17538;31.57410,46.17268
Haradu|34.46142,41.58539;34.46048,41.58603;34.46107,41.58725;34.46196,41.58657;34.46142,41.58539
Hattuša|40.01801,34.62078;40.01854,34.62026;40.01873,34.61956;40.01933,34.62001;40.01985,34.62003;40.02190,34.62070;40.02263,34.62135;40.02367,34.62235;40.02409,34.62245;40.02438,34.62231;40.02518,34.62128;40.02585,34.61714;40.02538,34.61328;40.02250,34.61091;40.02150,34.61062;40.02069,34.61084;40.01947,34.61294;40.01812,34.61242;40.01767,34.61160;40.01667,34.61126;40.01571,34.61047;40.01509,34.61036;40.01457,34.61050;40.01456,34.61048;40.01418,34.61010;40.01417,34.61011;40.01373,34.60972;40.01337,34.60980;40.01304,34.60945;40.01254,34.60937;40.01219,34.60971;40.01182,34.60972;40.01112,34.60969;40.01048,34.60977;40.01000,34.61003;40.00998,34.61003;40.00958,34.61028;40.00887,34.61112;40.00653,34.61503;40.00634,34.61538;40.00633,34.61542;40.00621,34.61617;40.00624,34.61693;40.00642,34.61789;40.00789,34.62171;40.00871,34.62261;40.01030,34.62269;40.01123,34.62282;40.01150,34.62329;40.01204,34.62344;40.01269,34.62335;40.01359,34.62398;40.01444,34.62451;40.01479,34.62406;40.01482,34.62328;40.01474,34.62223;40.01538,34.62161;40.01541,34.62053;40.01569,34.62072;40.01606,34.62089;40.01641,34.62107;40.01650,34.62100;40.01667,34.62070;40.01692,34.62047;40.01801,34.62078
Hazor|33.01798,35.57085;33.01827,35.57085;33.01866,35.57063;33.01937,35.57004;33.01968,35.57056;33.01994,35.57094;33.02045,35.57096;33.02196,35.56999;33.02220,35.56973;33.02216,35.56934;33.02210,35.56897;33.02207,35.56851;33.02256,35.56801;33.02611,35.56520;33.02618,35.56493;33.02612,35.56467;33.02598,35.56436;33.02387,35.56053;33.02344,35.56021;33.02341,35.56021;33.02299,35.55998;33.02244,35.55988;33.02242,35.55988;33.02194,35.56005;33.01663,35.56510;33.01583,35.56591;33.01611,35.56889;33.01644,35.56938;33.01768,35.57066;33.01798,35.57085
Isin|31.89378,45.27427;31.89383,45.27364;31.89360,45.27276;31.89233,45.26984;31.89071,45.26657;31.88784,45.26376;31.88562,45.26174;31.88504,45.26146;31.88338,45.26244;31.88127,45.26388;31.87817,45.26625;31.87802,45.26672;31.87845,45.26794;31.87980,45.27074;31.88067,45.27354;31.88114,45.27502;31.88240,45.27595;31.88344,45.27609;31.88988,45.27514;31.89272,45.27499;31.89355,45.27469;31.89378,45.27427
Kalhu|36.10610,43.32581;36.09622,43.32674;36.09268,43.34527;36.09297,43.34768;36.09627,43.34922;36.09616,43.35007;36.09782,43.35036;36.11031,43.34982;36.11005,43.33423;36.10955,43.32651;36.10610,43.32581
Karkemish|36.83103,38.01017;36.82928,38.00820;36.82258,38.01049;36.82164,38.01230;36.82205,38.01662;36.82226,38.01671;36.82334,38.02071;36.82729,38.01973;36.82740,38.01952;36.83048,38.01840;36.83080,38.01811;36.83159,38.01728;36.83219,38.01638;36.83228,38.01613;36.83230,38.01560;36.83224,38.01466;36.83205,38.01326;36.83118,38.01213;36.83104,38.01162;36.83103,38.01017
Lagaš|31.42579,46.42244;31.42964,46.42271;31.43103,46.42173;31.43248,46.41544;31.43486,46.41127;31.43698,46.40660;31.43699,46.40583;31.43311,46.40849;31.42894,46.40984;31.42579,46.40899;31.41280,46.40184;31.40855,46.39985;31.40573,46.40036;31.40395,46.40214;31.40280,46.40537;31.40334,46.40940;31.40493,46.41204;31.40758,46.41301;31.42579,46.42244
Larsa|31.29217,45.85672;31.29301,45.85522;31.29286,45.85250;31.29176,45.84939;31.28908,45.84713;31.28731,45.84661;31.28496,45.84595;31.28304,45.84582;31.28015,45.84684;31.27782,45.84945;31.27633,45.85263;31.27660,45.85496;31.27695,45.85892;31.28088,45.86164;31.28416,45.86291;31.28609,45.86309;31.28913,45.86095;31.29069,45.85846;31.29217,45.85672
Mari|34.55493,40.88132;34.55298,40.88148;34.55176,40.88084;34.54957,40.88116;34.54788,40.88235;34.54604,40.88427;34.54490,40.88629;34.54443,40.88744;34.54340,40.88792;34.54269,40.88888;34.54287,40.88981;34.54340,40.89055;34.54393,40.89164;34.54408,40.89202;34.54715,40.89317;34.54992,40.89353;34.55171,40.89222;34.55284,40.89020;34.55382,40.88841;34.55443,40.88549;34.55493,40.88132
Nineveh|36.36738,43.14141;36.35596,43.15084;36.34795,43.15917;36.34096,43.16640;36.33706,43.16889;36.33658,43.17838;36.36261,43.17312;36.37194,43.16721;36.37788,43.16044;36.36738,43.14141
Nippur|32.12876,45.22535;32.12676,45.22236;32.12515,45.22340;32.12423,45.22371;32.12204,45.22362;32.11956,45.22424;32.11721,45.22542;32.11858,45.22704;32.12139,45.22859;32.12338,45.23060;32.12341,45.23516;32.12598,45.23631;32.12777,45.23855;32.13322,45.23193;32.13017,45.22702;32.12919,45.22730;32.12876,45.22535
Qatna|34.83114,36.86060;34.83029,36.86510;34.82974,36.86553;34.83010,36.87186;34.83465,36.87193;34.83944,36.87111;34.83919,36.85970;34.83114,36.86060
Šaduppûm|33.30929,44.46598;33.30937,44.46767;33.31061,44.46720;33.31019,44.46556;33.30929,44.46598
Sikanu|36.83925,40.07242;36.83936,40.07280;36.83960,40.07296;36.83971,40.07456;36.84120,40.07460;36.84157,40.07463;36.84229,40.07460;36.84247,40.07451;36.84272,40.07423;36.84333,40.07340;36.84351,40.07312;36.84384,40.07247;36.84420,40.07216;36.84451,40.07158;36.84464,40.07129;36.84469,40.07106;36.84502,40.07041;36.84533,40.06971;36.84596,40.06853;36.84612,40.06819;36.84658,40.06688;36.84651,40.06590;36.84610,40.06497;36.84611,40.06490;36.84548,40.06386;36.84426,40.06285;36.84365,40.06257;36.84309,40.06242;36.84109,40.06256;36.83957,40.06303;36.83937,40.06313;36.83916,40.06338;36.83910,40.06373;36.83920,40.07153;36.83925,40.07242
Sippar|33.06119,44.24709;33.05466,44.25071;33.05969,44.26221;33.06576,44.25869;33.06119,44.24709
Sippar-dūrim|33.10291,44.29506;33.10205,44.29478;33.10108,44.29509;33.09951,44.29549;33.09809,44.29620;33.09727,44.29684;33.09542,44.29924;33.09929,44.30542;33.10041,44.30351;33.10152,44.30052;33.10239,44.29822;33.10355,44.29569;33.10291,44.29506
Wall 1|33.15889,44.18902;33.14684,44.21623;33.14474,44.22176;33.11884,44.27694;33.12500,44.28598;33.13852,44.29372;33.14535,44.32946
Šuruppak|31.78260,45.50247;31.78138,45.50252;31.78003,45.50313;31.77695,45.50479;31.77309,45.50648;31.77093,45.50791;31.76956,45.50937;31.76962,45.51077;31.77045,45.51201;31.77153,45.51306;31.77241,45.51456;31.77408,45.51587;31.77693,45.51741;31.77785,45.51753;31.77860,45.51682;31.78043,45.51429;31.78257,45.51185;31.78418,45.50869;31.78420,45.50560;31.78340,45.50302;31.78260,45.50247
Tuttul|35.95637,39.04327;35.95575,39.04376;35.95543,39.04472;35.95580,39.04720;35.95592,39.04936;35.95655,39.05057;35.95717,39.05088;35.95824,39.05094;35.95929,39.05053;35.96034,39.05034;35.96068,39.04917;35.96073,39.04806;35.96041,39.04667;35.96011,39.04566;35.95936,39.04455;35.95777,39.04360;35.95637,39.04327
Ugarit|35.60232,35.78227;35.60202,35.78222;35.60133,35.78229;35.60076,35.78246;35.60002,35.78277;35.59991,35.78338;35.60012,35.78611;35.60063,35.78775;35.60142,35.78810;35.60292,35.78792;35.60413,35.78750;35.60454,35.78692;35.60438,35.78609;35.60297,35.78309;35.60266,35.78252;35.60232,35.78227
Ur|30.96060,46.10159;30.95846,46.10256;30.95758,46.10340;30.95627,46.10511;30.95586,46.10650;30.95597,46.10732;30.95653,46.10812;30.95847,46.10920;30.96113,46.10933;30.96237,46.10902;30.96329,46.10843;30.96423,46.10762;30.96616,46.10554;30.96621,46.10509;30.96517,46.10303;30.96332,46.10055;30.96060,46.10159
Uruk|31.33678,45.63875;31.32934,45.62826;31.32827,45.62694;31.32653,45.62645;31.32533,45.62516;31.32474,45.62487;31.32126,45.62564;31.31773,45.62677;31.31551,45.62827;31.31424,45.62965;31.31377,45.63204;31.31312,45.63529;31.31158,45.63840;31.31058,45.64040;31.30967,45.64171;31.30958,45.64266;31.30991,45.64348;31.31041,45.64425;31.31162,45.64521;31.31259,45.64574;31.31465,45.64671;31.32102,45.65166;31.32190,45.65216;31.32260,45.65230;31.32330,45.65233;31.32544,45.65180;31.32890,45.65002;31.33023,45.64940;31.33139,45.64917;31.33193,45.64858;31.33257,45.64714;31.33365,45.64581;31.33539,45.64382;31.33665,45.64148;31.33687,45.63986;31.33678,45.63875
Umma|31.67193,45.88280;31.67028,45.87999;31.66933,45.87977;31.66734,45.87927;31.66528,45.87951;31.66265,45.87997;31.66049,45.88433;31.65939,45.88884;31.65873,45.89306;31.65914,45.89570;31.65971,45.89641;31.66199,45.89858;31.66504,45.89815;31.66910,45.89776;31.67286,45.89530;31.67475,45.89192;31.67437,45.88800;31.67280,45.88493;31.67193,45.88280
Zabalam|31.74395,45.87013;31.74355,45.87109;31.74284,45.87222;31.74149,45.87412;31.74038,45.87683;31.73976,45.87808;31.73923,45.87981;31.73784,45.88187;31.73637,45.88423;31.73537,45.88748;31.73651,45.88731;31.73988,45.88630;31.74323,45.88430;31.74453,45.88266;31.74634,45.88107;31.74710,45.87839;31.74741,45.87643;31.74741,45.87633;31.74735,45.87465;31.74672,45.87255;31.74485,45.86993;31.74395,45.87013
Borsippa|32.39483,44.33348;32.38333,44.33973;32.39006,44.35411;32.39983,44.34817;32.39483,44.33348
Kish|32.55644,44.57801;32.55240,44.57602;32.54888,44.58601;32.55305,44.58814;32.55644,44.57801
Hursagkalama|32.54184,44.59768;32.53972,44.59802;32.53836,44.59949;32.53715,44.60312;32.53850,44.60639;32.54049,44.60720;32.54199,44.60710;32.54384,44.59846;32.54184,44.59768
Kuta|32.76177,44.60847;32.76072,44.60727;32.75776,44.60743;32.75655,44.61205;32.75686,44.61368;32.75894,44.61549;32.76279,44.61530;32.76510,44.61201;32.76520,44.60943;32.76177,44.60847
Dilbat|32.29779,44.46187;32.29684,44.46152;32.29680,44.46152;32.29592,44.46179;32.29518,44.46260;32.29319,44.46748;32.29309,44.47014;32.29384,44.47070;32.29465,44.47088;32.29562,44.47086;32.29670,44.47045;32.29767,44.46987;32.29838,44.46926;32.29888,44.46859;32.29908,44.46726;32.29832,44.46297;32.29779,44.46187
Marad|32.09412,44.78190;32.09357,44.78099;32.09262,44.78094;32.09139,44.78142;32.08891,44.78621;32.09068,44.79007;32.09297,44.78822;32.09352,44.78763;32.09387,44.78696;32.09411,44.78612;32.09444,44.78345;32.09412,44.78190
"""

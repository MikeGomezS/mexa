# ============================================================
#  MEXA — Base de conocimiento verificado (RAG simple)
#  Cada tema tiene palabras clave y hechos curados manualmente.
#  El contexto se inyecta en la pregunta antes de enviarla a la IA.
# ============================================================

_BASE: list[dict] = [
    {
        "tema": "teotihuacan",
        "palabras_clave": [
            "teotihuacán", "teotihuacan",
            "pirámide del sol", "pirámide de la luna",
            "calzada de los muertos", "quetzalcóatl",
            "serpiente emplumada", "ciudad de los dioses",
        ],
        "hechos": (
            "Teotihuacán es una ciudad mesoamericana; pertenece a la cultura teotihuacana. "
            "Fundada ~100 a.C. en el actual Estado de México, a 50 km al noreste de la Ciudad de México. "
            "Fue la ciudad más grande de Mesoamérica y una de las más grandes del mundo antiguo, con ~200,000 habitantes en su apogeo (siglos IV-V d.C.). "
            "Sus monumentos principales son la Pirámide del Sol (tercer pirámide más grande del mundo, 65 m de altura), "
            "la Pirámide de la Luna (43 m) y el Templo de la Serpiente Emplumada (Quetzalcóatl), unidos por la Calzada de los Muertos (4 km de longitud). "
            "'Teotihuacán' es nombre náhuatl que significa 'lugar donde los hombres se convierten en dioses'; se desconoce cómo se llamaba originalmente. "
            "La Pirámide del Sol está alineada con el punto donde el Sol se pone el 19-20 de mayo y 24-25 de julio, fechas clave en su calendario. "
            "Bajo la Pirámide del Sol existe un túnel natural de ~100 m de largo, posiblemente usado en rituales. "
            "Tenía un sistema de drenaje sofisticado, calles trazadas en cuadrícula y más de 2,000 apartamentos residenciales. "
            "Sus habitantes comerciaban obsidiana, cerámica y plumas con pueblos de todo Mesoamérica. "
            "Los murales de Tetitla y Tepantitla muestran escenas de la vida cotidiana y religiosa en colores vivos. "
            "En 2003 se descubrió el túnel de Tlalocan bajo el Templo de Quetzalcóatl, con miles de objetos rituales. "
            "Fue abandonada ~550 d.C.; incendios internos sugieren revueltas o colapso social, no invasión externa. "
            "Los aztecas la encontraron ya abandonada y la consideraron sagrada, lugar donde los dioses crearon el quinto sol. "
            "Patrimonio Mundial UNESCO desde 1987. Recibe ~4 millones de visitantes al año."
        ),
    },
    {
        "tema": "aztecas",
        "palabras_clave": [
            "azteca", "aztecas", "mexica", "mexicas",
            "tenochtitlán", "tenochtitlan",
            "templo mayor", "huitzilopochtli", "tláloc",
            "moctezuma", "cuauhtémoc", "cuauhtemoc",
            "hernán cortés", "hernan cortes",
            "quinto sol", "chinampas", "calendario azteca",
            "piedra del sol", "triple alianza",
            "noche triste", "cacao", "chocolate",
        ],
        "hechos": (
            "Los aztecas (también llamados mexicas) fundaron Tenochtitlán en 1325 d.C. en un islote del lago Texcoco, "
            "donde hoy está el Zócalo de la Ciudad de México. "
            "Guiados por la profecía de un águila devorando una serpiente sobre un nopal, que hoy aparece en la bandera mexicana. "
            "Formaron la Triple Alianza con Texcoco y Tlacopan en 1428, construyendo el mayor imperio de Mesoamérica. "
            "El Templo Mayor era el centro religioso, dedicado a Huitzilopochtli (dios del sol y la guerra) "
            "y Tláloc (dios de la lluvia); tenía 40 m de altura y fue reconstruido 7 veces. "
            "Desarrollaron las chinampas ('jardines flotantes'), islas artificiales para cultivo en el lago, "
            "que permitieron alimentar a una ciudad de ~200,000 habitantes. "
            "La Piedra del Sol ('Calendario Azteca') tiene 3.6 m de diámetro y 24 toneladas; "
            "no es un calendario funcional sino una representación cosmológica del quinto sol. "
            "Hernán Cortés llegó en 1519; Moctezuma II gobernaba entonces. "
            "La Noche Triste (30 junio–1 julio 1520): los españoles fueron expulsados de Tenochtitlán con grandes bajas. "
            "Cuauhtémoc fue el último tlatoani azteca; defendió Tenochtitlán hasta su captura el 13 agosto 1521. "
            "Fue torturado para revelar tesoros escondidos y ejecutado en 1525. "
            "El cacao era moneda de cambio y la base del chocolate; los aztecas lo bebían amargo y frío. "
            "Tenían un sistema de escritura pictográfico, matemáticas en base 20, y un calendario de 365 días (xiuhpohualli). "
            "El 13 agosto se conmemora como Día de la Caída de Tenochtitlán."
        ),
    },
    {
        "tema": "mayas",
        "palabras_clave": [
            "maya", "mayas",
            "chichén itzá", "chichen itza", "chichén",
            "palenque", "uxmal", "tikal", "tulum", "cobá",
            "calendario maya", "cenote", "popol vuh",
            "kukulcán", "el castillo", "juego de pelota",
            "escritura maya", "cero maya",
        ],
        "hechos": (
            "Los mayas son una civilización mesoamericana que floreció en el sureste de México "
            "(Yucatán, Quintana Roo, Chiapas, Tabasco, Campeche) y Centroamérica (Guatemala, Belice, Honduras). "
            "No son el mismo pueblo que los teotihuacanos ni los aztecas; tienen idioma, escritura y dioses propios. "
            "Su período Clásico abarca del 250 al 900 d.C., con ciudades como Palenque, Tikal, Copán y Calakmul. "
            "Fueron los únicos mesoamericanos en desarrollar un sistema de escritura completamente fonético: glifos mayas. "
            "Inventaron el concepto del cero de forma independiente, antes que Europa. "
            "Su calendario Tzolkin (260 días rituales) y Haab (365 días solares) son de gran precisión astronómica. "
            "El 'fin del mundo maya' en 2012 fue una interpretación errónea: solo marcaba el fin de un ciclo de 5,125 años. "
            "Chichén Itzá (Yucatán) es su sitio más famoso: la Pirámide de Kukulcán (El Castillo) tiene 91 escalones "
            "por cada lado (364 en total + plataforma superior = 365, uno por día del año). "
            "En los equinoccios, la sombra de la pirámide forma una serpiente descendiendo por la escalera norte. "
            "Chichén Itzá fue elegida una de las 7 Maravillas del Mundo Moderno en 2007. "
            "Los cenotes (pozos naturales de agua dulce) eran sagrados para los mayas; el Cenote Sagrado de Chichén "
            "recibía ofrendas y, en tiempos de crisis, sacrificios rituales. "
            "El Popol Vuh es el libro sagrado maya-k'iche' que narra la creación del mundo y de los hombres de maíz. "
            "El juego de pelota maya (pitz) se jugaba en todas las ciudades; el capitán del equipo perdedor era sacrificado. "
            "Los mayas NUNCA desaparecieron: hoy hay ~8 millones de personas de descendencia maya en México y Centroamérica. "
            "Palenque (Chiapas) alberga la tumba del rey Pakal, descubierta en 1952, con un sarcófago de piedra de 5 toneladas."
        ),
    },
    {
        "tema": "olmecas",
        "palabras_clave": [
            "olmeca", "olmecas",
            "cabeza colosal", "cabezas colosales",
            "san lorenzo", "la venta", "tres zapotes",
            "cultura madre", "hule", "goma",
        ],
        "hechos": (
            "Los olmecas fueron la primera gran civilización de Mesoamérica (~1500–400 a.C.), "
            "considerada la 'cultura madre' por haber influido en mayas, aztecas y otras culturas posteriores. "
            "Su nombre significa 'pueblo del hule (caucho)' en náhuatl; eran expertos en trabajar la goma natural. "
            "Se desarrollaron en la costa del Golfo de México: Veracruz y Tabasco. "
            "Sus principales centros fueron San Lorenzo (~1200 a.C.), La Venta (~900 a.C.) y Tres Zapotes (~900 a.C.). "
            "Son famosos por las 17 Cabezas Colosales descubiertas: esculturas de basalto de hasta 3 m de altura "
            "y 8–40 toneladas que representan a gobernantes olmecas con rasgos individuales únicos. "
            "El basalto fue transportado desde los cerros de Los Tuxtlas (~100 km) sin rueda ni animales de carga. "
            "Desarrollaron los primeros sistemas de escritura y calendarios de Mesoamérica. "
            "El motivo del 'hombre-jaguar' (niño con rasgos de jaguar) es el símbolo religioso más característico. "
            "Inventaron el juego de pelota mesoamericano, adoptado después por mayas y aztecas. "
            "Crearon figurillas de jade y espejos de ilmenita y magnetita con precisión milimétrica. "
            "La causa de su declive es desconocida; algunos sitios muestran evidencias de destrucción intencional de monumentos. "
            "El Museo de Antropología de Xalapa, Veracruz, alberga la mayor colección de escultura olmeca del mundo."
        ),
    },
    {
        "tema": "toltecas",
        "palabras_clave": [
            "tolteca", "toltecas",
            "tula", "tollan",
            "atlantes de tula", "atlantes",
            "ce ácatl", "ce acatl", "topiltzin",
            "quetzalcóatl tolteca",
            "cultura tolteca",
        ],
        "hechos": (
            "Los toltecas fueron una civilización mesoamericana que floreció aproximadamente entre 800 y 1150 d.C., "
            "con capital en Tula (Tollan), en el actual estado de Hidalgo, a 80 km al norte de la Ciudad de México. "
            "Los aztecas los consideraban los creadores de toda arte, conocimiento y civilización; "
            "'tolteca' en náhuatl significa 'maestro artesano' o 'el que construye con perfección'. "
            "Su gobernante más famoso fue Ce Ácatl Topiltzin Quetzalcóatl, figura histórica y mítica a la vez: "
            "sacerdote-rey que adoptó el nombre del dios Quetzalcóatl y se convirtió en símbolo cultural. "
            "Según la leyenda, Quetzalcóatl fue expulsado de Tula por rivales y prometió regresar; "
            "esta profecía influyó en la recepción de Hernán Cortés por parte de los aztecas en 1519. "
            "Tula es famosa por los Atlantes: cuatro guerreros de basalto de 4.6 m de altura "
            "que sostenían el techo del Templo de Tlahuizcalpantecuhtli (estrella matutina). "
            "Los toltecas introdujeron el culto al dios Tezcatlipoca ('espejo humeante'), rival de Quetzalcóatl. "
            "Hay evidencias de influencia tolteca en Chichén Itzá: el Templo de los Guerreros y los Chac Mool "
            "son similares a los de Tula, aunque el debate sobre si hubo conquista o intercambio cultural continúa. "
            "Trabajaban la obsidiana, el metal y practicaban el sacrificio humano de forma ritual. "
            "Tula fue destruida e incendiada alrededor de 1150-1200 d.C., posiblemente por invasiones chichimecas o conflictos internos. "
            "Los aztecas reclamaban descender de los toltecas para legitimar su poder político y religioso."
        ),
    },
    {
        "tema": "zapotecas",
        "palabras_clave": [
            "zapoteca", "zapotecas",
            "monte albán", "monte alban",
            "oaxaca", "dainzú", "mitla",
            "urna funeraria", "glifos zapotecos",
            "cultura zapoteca", "valle de oaxaca",
        ],
        "hechos": (
            "Los zapotecas son una de las civilizaciones más antiguas de Mesoamérica, "
            "originados en los valles centrales de Oaxaca alrededor de 500 a.C. "
            "Su capital fue Monte Albán, construida sobre una montaña artificial aplanada ~500 a.C., "
            "considerada una de las primeras ciudades planificadas de Mesoamérica. "
            "En su apogeo (200-700 d.C.) Monte Albán tenía ~25,000 habitantes y dominaba la región. "
            "Los zapotecas desarrollaron uno de los primeros sistemas de escritura de Mesoamérica: "
            "glifos que combinaban logogramas y fonogramas, usados para registrar calendarios y genealogías. "
            "Su arquitectura en Monte Albán incluye plataformas, juegos de pelota, observatorios astronómicos "
            "y el Edificio J, alineado con la salida helíaca de estrellas específicas. "
            "Eran conocidos por sus urnas funerarias de cerámica gris, colocadas en tumbas junto a los muertos "
            "y decoradas con representaciones de Cocijo, dios zapoteca de la lluvia. "
            "Monte Albán decayó alrededor de 700-800 d.C.; los mixtecas reutilizaron sus tumbas siglos después. "
            "Los zapotecas se enfrentaron militarmente a los aztecas antes de la llegada española, "
            "sin ser completamente conquistados. "
            "Monte Albán es Patrimonio Mundial UNESCO desde 1987. "
            "Hoy los zapotecas siguen siendo el pueblo indígena más numeroso de Oaxaca, con ~800,000 hablantes de lenguas zapotecas."
        ),
    },
    {
        "tema": "mixtecas",
        "palabras_clave": [
            "mixteca", "mixtecas",
            "pueblo de las nubes",
            "códice mixteca", "códice nuttall", "códice vindobonensis",
            "8 venado", "ocho venado", "garra de jaguar",
            "tilantongo", "coixtlahuaca",
            "orfebres", "orfebrería mixteca",
            "cultura mixteca",
        ],
        "hechos": (
            "Los mixtecas son una civilización mesoamericana originaria del noroeste de Oaxaca "
            "y partes de Guerrero y Puebla; 'mixteco' en náhuatl significa 'pueblo de las nubes'. "
            "Alcanzaron su apogeo entre 900 y 1521 d.C., con centros como Tilantongo, Teposcolula y Coixtlahuaca. "
            "Son reconocidos como los mejores orfebres de toda Mesoamérica: trabajaban el oro, la plata, "
            "la turquesa, el jade y el hueso con una precisión y elaboración sin igual en el continente. "
            "El Tesoro de Monte Albán (Tumba 7), descubierto en 1932, es la mayor colección de joyería mixteca: "
            "más de 500 objetos de oro, turquesa, hueso y jade depositados por los mixtecas en una tumba zapoteca. "
            "Produjeron los códices más elaborados de Mesoamérica: el Códice Nuttall, el Códice Vindobonensis "
            "y el Códice Bodley narran genealogías reales, calendarios rituales y hazañas militares con imágenes policromadas. "
            "Su figura histórica más importante fue 8 Venado Garra de Jaguar (1063–1115 d.C.), "
            "guerrero-gobernante que unificó mediante conquistas y alianzas gran parte de la Mixteca Alta. "
            "Los mixtecas convivieron y compitieron con los zapotecas; ocuparon Monte Albán como cementerio real. "
            "Fueron tributarios del Imperio Azteca antes de la conquista española, pero nunca completamente sometidos. "
            "Hoy hay ~500,000 hablantes de lenguas mixtecas en México, Oaxaca, Guerrero y Puebla principalmente. "
            "Su tradición artesanal continúa: los mixtecas de Teotitlán del Valle son famosos por sus tapetes de lana "
            "y los de Tilcajete por sus figuras alebrijes pintadas a mano."
        ),
    },
    {
        "tema": "independencia",
        "palabras_clave": [
            "independencia", "independencia de méxico",
            "hidalgo", "miguel hidalgo",
            "morelos", "josé maría morelos",
            "josefa ortiz", "josefa ortiz de domínguez", "corregidora",
            "leona vicario",
            "agustín de iturbide", "iturbide",
            "vicente guerrero",
            "plan de iguala",
            "grito de independencia", "grito de dolores",
            "guerra de independencia",
            "1810", "1821", "16 de septiembre",
            "ejército trigarante", "conspiración de querétaro",
        ],
        "hechos": (
            "La Guerra de Independencia de México duró del 16 de septiembre de 1810 al 27 de septiembre de 1821. "
            "La Conspiración de Querétaro (1810): un grupo de criollos planeaba el levantamiento; "
            "Josefa Ortiz de Domínguez ('La Corregidora') avisó a Hidalgo cuando la conspiración fue descubierta. "
            "El 16 de septiembre de 1810, el cura Miguel Hidalgo dio el 'Grito de Dolores' en Dolores, Guanajuato, "
            "convocando al pueblo a luchar. Por eso el 16 de septiembre es el Día de la Independencia Nacional. "
            "Hidalgo reunió un ejército popular de ~80,000 personas con el estandarte de la Virgen de Guadalupe. "
            "Hidalgo fue capturado, degradado y fusilado el 30 de julio de 1811 en Chihuahua. "
            "José María Morelos retomó el liderazgo; fue sacerdote, militar estratega y estadista. "
            "Morelos organizó el Congreso de Chilpancingo (1813) donde se declaró la independencia y se redactó "
            "el 'Solemne Acta de Declaración de Independencia de la América Septentrional'. "
            "Morelos fue capturado, degradado y fusilado el 22 de diciembre de 1815. "
            "Leona Vicario fue heroína insurgente: financió la causa, fabricó municiones y fue espía. "
            "Agustín de Iturbide, oficial realista que se unió a los insurgentes, firmó el Plan de Iguala (24 feb 1821) "
            "con tres garantías: independencia, religión católica e igualdad entre criollos y peninsulares. "
            "Vicente Guerrero, insurgente que no se rindió, se unió a Iturbide para consumar la independencia. "
            "El 27 de septiembre de 1821, el Ejército Trigarante (verde, blanco y rojo) entró triunfante a la CDMX. "
            "México fue el primer país latinoamericano en independizarse de España en forma definitiva. "
            "Iturbide se proclamó Emperador Agustín I en 1822 y fue depuesto en 1823, exiliado y fusilado en 1824."
        ),
    },
    {
        "tema": "revolucion",
        "palabras_clave": [
            "revolución", "revolución mexicana",
            "zapata", "emiliano zapata",
            "villa", "pancho villa", "francisco villa",
            "madero", "francisco madero",
            "carranza", "venustiano carranza",
            "obregón", "álvaro obregón", "alvaro obregon",
            "porfirio díaz", "porfiriato",
            "flores magón", "ricardo flores magón",
            "plan de san luis", "plan de ayala",
            "división del norte",
            "1910", "1917", "constitución de 1917",
            "tierra y libertad",
        ],
        "hechos": (
            "La Revolución Mexicana comenzó el 20 de noviembre de 1910, fecha que hoy se conmemora como el "
            "Día de la Revolución. "
            "Porfirio Díaz gobernó México durante 30 años (1876–1911), período conocido como el Porfiriato; "
            "modernizó la economía pero concentró la riqueza y suprimió derechos políticos. "
            "Ricardo Flores Magón y el Partido Liberal Mexicano (PLM) sembraron las ideas anarquistas y magonistas "
            "que inspiraron a los revolucionarios desde 1905. "
            "Francisco I. Madero lanzó el Plan de San Luis (5 oct 1910), convocando al pueblo a levantarse el 20 nov. "
            "Porfirio Díaz renunció y se exilió en Francia el 25 mayo 1911; murió en París en 1915. "
            "Madero fue presidente (1911–1913) pero fue traicionado y asesinado por Victoriano Huerta en la 'Decena Trágica'. "
            "Emiliano Zapata lideró el movimiento agrarista del sur (Morelos) bajo el Plan de Ayala (1911) "
            "y el lema 'Tierra y Libertad'; exigía devolución de tierras a los campesinos. "
            "Zapata fue asesinado en una emboscada en Chinameca, Morelos, el 10 de abril de 1919. "
            "Francisco Villa ('Pancho Villa') comandó la División del Norte, el ejército más poderoso de la revolución; "
            "llegó a tener 40,000 hombres y tomó ciudades como Zacatecas (1914). "
            "Villa fue asesinado en su rancho de Parral, Chihuahua, el 20 de julio de 1923. "
            "Venustiano Carranza convocó el Congreso Constituyente de 1916–1917 en Querétaro. "
            "La Constitución de 1917 fue la primera en el mundo en incluir derechos sociales: "
            "reforma agraria (Art. 27), derechos laborales (Art. 123), educación pública laica (Art. 3). "
            "Álvaro Obregón derrotó a Carranza, quien fue asesinado en 1920; Obregón gobernó 1920–1924. "
            "El conflicto armado principal terminó ~1920, aunque la inestabilidad política continuó hasta ~1929 "
            "con la fundación del PNR (antecedente del PRI)."
        ),
    },
    {
        "tema": "mexico_general",
        "palabras_clave": [
            "méxico", "mexico",
            "bandera de méxico", "bandera mexicana",
            "himno nacional", "himno nacional mexicano",
            "águila", "serpiente", "nopal", "escudo nacional",
            "capital de méxico", "ciudad de méxico", "cdmx",
            "geografía de méxico", "estados de méxico",
            "día de muertos", "dia de muertos",
            "mariachi", "tequila", "mezcal",
            "gastronomía mexicana", "comida mexicana",
            "popocatépetl", "iztaccíhuatl", "volcán",
            "megadiverso", "biodiversidad",
            "patrimonio unesco", "sitios patrimonio",
        ],
        "hechos": (
            "México es una república federal de 31 estados más la Ciudad de México como capital federal. "
            "Tiene ~130 millones de habitantes (2024), siendo el undécimo país más poblado del mundo. "
            "Es el país con más hispanohablantes del mundo. "
            "— BANDERA Y SÍMBOLOS —\n"
            "La bandera tiene tres franjas verticales: verde (esperanza), blanco (unidad), rojo (sangre de los héroes). "
            "El escudo muestra un águila real devorando una serpiente sobre un nopal en un lago, "
            "símbolo de la fundación mexica de Tenochtitlán. "
            "El Himno Nacional fue adoptado en 1854; letra de Francisco González Bocanegra, música de Jaime Nunó. "
            "— GEOGRAFÍA —\n"
            "México tiene 1,964,375 km², siendo el décimo cuarto país más grande del mundo. "
            "Limita al norte con EE.UU. (3,185 km de frontera), al sur con Guatemala y Belice. "
            "Tiene 11,122 km de costas: Océano Pacífico al oeste, Golfo de México y Mar Caribe al este. "
            "El Popocatépetl (5,452 m) y el Iztaccíhuatl (5,230 m) son los volcanes más famosos, cerca de la CDMX. "
            "El Pico de Orizaba (Citlaltépetl, 5,636 m) es el punto más alto de México y tercero de Norteamérica. "
            "Es uno de los 17 países 'megadiversos': alberga ~10% de las especies de todo el planeta. "
            "— CULTURA Y PATRIMONIO —\n"
            "México tiene 35 sitios Patrimonio Mundial UNESCO, el más alto de América Latina. "
            "El Día de Muertos (1-2 noviembre) es Patrimonio Cultural Inmaterial de la Humanidad UNESCO (2008). "
            "El mariachi es Patrimonio Cultural Inmaterial UNESCO (2011). "
            "La gastronomía mexicana es Patrimonio Cultural Inmaterial UNESCO (2010); "
            "incluye el maíz como base, el mole (más de 200 variedades), el chile (más de 60 tipos) y el chocolate. "
            "El tequila se produce exclusivamente en Jalisco y 4 estados más, con Agave tequilana Weber. "
            "El mezcal puede producirse en 9 estados; a diferencia del tequila, puede ser de cualquier tipo de agave. "
            "La Ciudad de México fue fundada como Tenochtitlán en 1325 y refundada por los españoles en 1521. "
            "Es la ciudad más poblada de América del Norte (~22 millones en área metropolitana). "
            "México fue sede de los Juegos Olímpicos de 1968, primer país latinoamericano en serlo. "
            "El peso mexicano ($) es la moneda oficial desde 1863."
        ),
    },
]


_MAX_ORACIONES = 4  # hechos por tema que se inyectan al modelo


def _resumir(hechos: str) -> str:
    """Retorna las primeras _MAX_ORACIONES oraciones del bloque de hechos."""
    oraciones = [o.strip() for o in hechos.split(". ") if o.strip()]
    return ". ".join(oraciones[:_MAX_ORACIONES]) + "."


def buscar_contexto(pregunta: str) -> str:
    """
    Busca en la base de conocimiento hechos relevantes para la pregunta.
    Regresa un string con los hechos, o cadena vacía si no hay match.
    """
    pregunta_lower = pregunta.lower()
    encontrados = []

    for entrada in _BASE:
        for clave in entrada["palabras_clave"]:
            if clave in pregunta_lower:
                encontrados.append(_resumir(entrada["hechos"]))
                break  # un match por tema es suficiente

    if not encontrados:
        return ""

    return "Hechos verificados:\n" + "\n".join(f"- {h}" for h in encontrados)

# assets/welcome

Mensajes de bienvenida. Se elige **uno al azar** de esta carpeta (subcarpetas
incluidas) y se reproduce después de que arrancó la música.

Los audios no se versionan (ver `.gitignore` en la raíz). Poné acá los tuyos.

Extensiones soportadas: `.mp3`, `.wav`, `.ogg`, `.oga`, `.flac`, `.m4a`, `.opus`.

## Fijar el idioma

Por defecto elige entre todos los archivos. Para forzar un idioma, usá `include`
en el bloque `[[actions]]` de tipo `welcome` del `config.toml`: filtra por un
pedazo del nombre del archivo (por ejemplo `include = "Bienv"` para español).

Si preferís algo que no dependa de cómo se llamen los archivos, armá subcarpetas
`es/` y `en/` y apuntá `folder = "assets/welcome/es"`.

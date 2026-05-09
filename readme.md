# AnimeFLV Player

Aplicacion de escritorio en Python para buscar animes en AnimeFLV con una interfaz visual estilo streaming. La app ahora mezcla resultados de AnimeFLV con una segunda fuente secundaria basada en JkAnime para ampliar el catalogo inicial y las sugerencias aleatorias. Al iniciar muestra un catalogo tipo Top 10 para elegir un anime y luego pasa a la vista principal con portada, sinopsis, episodios y servidores disponibles. La reproduccion se abre en Brave, pero desde el flujo de la app.

## Caracteristicas

- Busqueda por titulo.
- Pantalla inicial de catalogo Top 10.
- Fuente secundaria JkAnime para ampliar el catalogo y el random.
- Hero principal con portada y ficha del anime.
- Tarjetas visuales de resultados.
- Lista de episodios.
- Lista de servidores por episodio.
- Apertura de reproduccion en Brave desde la app.
- Boton para volver al catalogo o al buscador sin salir del programa.
- Cache interna para evitar que AnimeFLV devuelva fichas vacias en peticiones repetidas.

## Instalacion

```bash
pip install -r requirements.txt
```

## Ejecucion

```bash
python main.py
```

## Nota

Este proyecto consume AnimeFLV directamente con `cloudscraper`, `beautifulsoup4` y `lxml` para extraer la informacion del sitio de forma estable, y usa JkAnime como segunda fuente secundaria para ampliar la experiencia de descubrimiento. Al seleccionar un anime en el catalogo, la app abre la vista principal ya cargada. Cuando seleccionas un servidor, el episodio se abre en Brave y puedes volver al catalogo o al buscador con un boton.

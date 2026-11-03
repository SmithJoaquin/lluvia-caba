# ¿Llueve o no llueve? — Buenos Aires

Página para el celular que responde si llueve en Capital y desde qué hora, juntando:

- **7 pronósticos** (europeo, EE. UU., alemán, canadiense, francés, británico, japonés) vía Open-Meteo: cuántos
  dicen lluvia hora por hora. La página los pide en vivo al abrirse.
- **Avisos del SMN** (formato CAP): alertas por zona y avisos a corto plazo (2 h) cuyo polígono incluye Capital, o
  los a corto plazo a menos de 60 km.
- **Partes de 6 aeropuertos de AMBA** (METAR de aviationweather.gov): si está lloviendo ahora.

Sitio: https://smithjoaquin.github.io/lluvia-caba/

## Cómo funciona

`generar.py` baja todo y deja `sitio/index.html` (la plantilla con los datos adentro) y `sitio/datos.json`.
`.github/workflows/actualizar.yml` lo corre cada 15 minutos (GitHub suele demorar los cron unos minutos) y publica
en GitHub Pages. La página relee `datos.json` al abrirse y con «Actualizar».

Local: `python generar.py` y abrir `sitio/index.html`. El mismo `index.html` sirve como artefacto de Claude: sin red
muestra los datos de adentro con un cartel de la hora en que se bajaron.

## Trampas conocidas

- El SMN y aviationweather **no mandan permiso de origen cruzado**: una página no los puede leer directo, por eso
  existe el intermediario. Open-Meteo sí, por eso el pronóstico va en vivo.
- El SMN **corta con 429** si se le piden muchos avisos seguidos: se piden de a uno con pausa, y cada aviso bajado
  se guarda (`cache_avisos/`, que el workflow conserva entre corridas). Si alguno no se pudo leer, la página lo dice
  en vez de afirmar que no hay avisos.
- Los **avisos a corto plazo** vienen con la hora UTC rotulada como -03:00: si se "emitieron en el futuro", se
  corrigen.
- El radar del SMN **no es accesible** en forma automática y permitida (barrera anti-robots y permiso por sesión);
  el acceso se pide a `odp-aws@smn.gov.ar`. RainViewer y Windy no lo tienen para AMBA.
- GitHub **apaga la programación** de un repo sin commits en 60 días: el workflow hace un commit vacío cada 50.
- Open-Meteo es gratis para uso **no comercial**. Si esto se vuelve un producto, hay que revisar su plan.

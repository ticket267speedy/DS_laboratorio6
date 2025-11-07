from flask import Flask, render_template, request
import requests

# Usamos el directorio actual como carpeta de templates para que funcione con lab6/index.html
app = Flask(__name__, template_folder='.')


@app.route('/', methods=['GET', 'POST'])
def index():
    """
    Se aplica los endpoints GET y POST
    - GET: Muestra el formulario.
    - POST: Va recibir el nombre del Pokémon, consulta PokeAPI y muestra tipos, movimientos y 4 sprites.
    """
    context = {
        'pokemon_name': None,
        'types': [],
        'moves': [],
        'sprites': {},
        'error_message': None,
    }

    if request.method == 'POST':
        nombre = request.form.get('pokemon', '').strip().lower()
        if not nombre:
            context['error_message'] = 'Ingresa un nombre de Pokémon.'
            return render_template('index.html', **context)

        url = f'https://pokeapi.co/api/v2/pokemon/{nombre}'
        try:
            resp = requests.get(url, timeout=20)
        except requests.exceptions.RequestException as e:
            context['error_message'] = f'Error de red consultando PokeAPI: {e}'
            return render_template('index.html', **context)

        if resp.status_code != 200:
            context['error_message'] = f"No se encontró el Pokémon '{nombre}' (HTTP {resp.status_code})."
            return render_template('index.html', **context)

        data = resp.json()

        # Tipos
        tipos = [t['type']['name'] for t in data.get('types', [])]

        # Movimientos, solo agarra los primeros 15
        movimientos = [m['move']['name'] for m in data.get('moves', [])][:15]

        # Sprites: dos de frente y dos de espalda (las imagenes que aparecen en default y shiny)
        sprites = data.get('sprites', {})
        imagenes = {
            'front_default': sprites.get('front_default'),
            'front_shiny': sprites.get('front_shiny'),
            'back_default': sprites.get('back_default'),
            'back_shiny': sprites.get('back_shiny'),
        }

        context.update({
            'pokemon_name': nombre,
            'types': tipos,
            'moves': movimientos,
            'sprites': imagenes,
        })

    return render_template('index.html', **context)


if __name__ == '__main__':
    app.run(debug=True)
    
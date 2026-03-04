from flask import Flask

app = Flask(__name__)
app.config['SERVER_NAME'] = 'example.com'

with app.app_context():
    from flask import current_app
    current_app.jinja_env.loader.searchpath.append('app/templates')
    print('compiling template...')
    try:
        tmpl = current_app.jinja_env.get_template('scouting/pit_form.html')
        print('template compiled successfully')
    except Exception as e:
        print('error compiling:', e)

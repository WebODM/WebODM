// Réplica de app/plugins/templates/webpack.config.js.tmpl de WebODM (mismas reglas, externals y
// versiones), pero ejecutable fuera de WebODM. El build resultante va dentro del zip: WebODM no
// compila un plugin que ya trae `public/build`, y así el zip funciona también donde no hay
// webpack, como la app de escritorio de Windows.
const fs = require('fs');
const path = require('path');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');

const pluginPublic = path.join(__dirname, '..', 'public');
const nodeModules = path.join(__dirname, 'node_modules');

// El panel importa `webodm/...` (ErrorMessage, Workers, gettext), que webpack incluye en el
// bundle: hace falta el código fuente de algún WebODM. WEBODM_DIR manda; si no, se usa el
// WebODM en el que vive este plugin (coreplugins/realign/packaging → raíz del repo) y luego las
// ubicaciones habituales.
const webodmCandidates = [
  process.env.WEBODM_DIR,
  path.join(__dirname, '..', '..', '..'), // raíz del repo de WebODM que contiene el plugin
  'C:/WebODM/resources/app/apps/WebODM',  // app de escritorio de Windows
  '/webodm',                               // contenedor Docker
].filter(Boolean);
const webodmDir = webodmCandidates.find(d =>
  fs.existsSync(path.join(d, 'app', 'static', 'app', 'js', 'classes', 'Workers.js')));
if (!webodmDir) {
  throw new Error('No se encontró el código de WebODM. Define WEBODM_DIR con la carpeta raíz de ' +
                  'WebODM (la que contiene app/static/app/js). Probadas: ' + webodmCandidates.join(', '));
}

module.exports = {
  mode: 'production',
  context: pluginPublic,
  entry: {"Realign": ["./Realign.jsx"]},
  output: {
    path: path.join(pluginPublic, 'build'),
    filename: "[name].js",
    libraryTarget: "amd",
    clean: true
  },
  plugins: [
    new MiniCssExtractPlugin({ filename: '[name].css', chunkFilename: '[id].css' })
  ],
  module: {
    rules: [
      {
        test: /\.jsx?$/,
        exclude: /(node_modules|bower_components)/,
        use: [{
          loader: 'babel-loader',
          options: {
            // El .babelrc del propio WebODM resolvería sus presets desde una carpeta sin
            // node_modules: la configuración va entera aquí.
            babelrc: false,
            configFile: false,
            plugins: ['@babel/syntax-class-properties', '@babel/proposal-class-properties'],
            presets: ['@babel/preset-env', '@babel/preset-react']
          }
        }]
      },
      {
        test: /\.s?css$/,
        use: [MiniCssExtractPlugin.loader, 'css-loader', 'sass-loader']
      },
      {
        test: /\.(png|jpg|jpeg|svg)/,
        use: { loader: 'url-loader', options: { limit: 100000 } }
      }
    ]
  },
  resolve: {
    modules: [nodeModules],
    extensions: ['.js', '.jsx'],
    alias: { webodm: path.join(webodmDir, 'app', 'static', 'app', 'js') }
  },
  resolveLoader: { modules: [nodeModules] },
  externals: {
    "jquery": "jQuery",
    "SystemJS": "SystemJS",
    "PluginsAPI": "PluginsAPI",
    "leaflet": "leaflet",
    "ReactDOM": "ReactDOM",
    "React": "React"
  }
};

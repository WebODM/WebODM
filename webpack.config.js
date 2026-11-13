const webpack = require('webpack');
let path = require("path");
let BundleTracker = require('webpack-bundle-tracker');
let MiniCssExtractPlugin = require("mini-css-extract-plugin");
let LiveReloadPlugin = require('webpack-livereload-plugin');


const mode = process.argv.indexOf("production") !== -1 ? "production" : "development";
console.log(`Webpack mode: ${mode}`);

module.exports = {
  mode,
  context: __dirname,

  entry: {
    main: ['./app/static/app/js/main.jsx'],
    Console: ['./app/static/app/js/Console.jsx'],
    Dashboard: ['./app/static/app/js/Dashboard.jsx'],
    MapView: ['./app/static/app/js/MapView.jsx'],
    ModelView: ['./app/static/app/js/ModelView.jsx'],
    PluginBrowser: ['./app/static/app/js/PluginBrowser.jsx']
  },

  output: {
    path: path.join(__dirname, './app/static/app/bundles/'),
    filename: "[name]-[hash].js",
    publicPath: '/static/app/bundles/'
  },

  plugins: [
    new LiveReloadPlugin({ appendScriptTag: true }),
    new BundleTracker({
      filename: 'webpack-stats.json',
      path: path.join(__dirname, './'),
    }),
    new MiniCssExtractPlugin({
      filename: "./css/[name]-[hash].css",
      chunkFilename: "[id].css"
    }),
    new webpack.ProvidePlugin({
      Buffer: ['buffer', 'Buffer'],
  }),
  ],

  module: {
    rules: [
      {
        test: /\.jsx?$/,
        exclude: /(node_modules|bower_components)/,
        use: [
          {
            loader: 'babel-loader',
            options: {
              plugins: [
                '@babel/syntax-class-properties',
                '@babel/proposal-class-properties'
              ],
              presets: [
                '@babel/preset-env',
                '@babel/preset-react'
              ]
            }
          }
        ],
      },
      {
        test: /\.s?css$/,
        use: [
          MiniCssExtractPlugin.loader,
          "css-loader",
          "sass-loader",
        ]
      },
      {
        test: /\.(png|jpg|jpeg|svg)/,
        use: {
          loader: 'url-loader',
          options: {
            limit: 100000,
          },
        },
      },
      {
        // shaders
        test: /\.(frag|vert|glsl)$/,
        loader: 'raw-loader'
      }
    ]
  },

  resolve: {
    modules: ['node_modules', 'bower_components'],
    extensions: ['.js', '.jsx'],
    fallback: {
      buffer: require.resolve('buffer'),
    }
  },

  externals: {
    // require("jquery") is external and available
    //  on the global let jQuery
    "jquery": "jQuery",
    "SystemJS": "SystemJS",
    "THREE": "THREE",
    "React": "React",
    "ReactDOM": "ReactDOM"
  },

  watchOptions: {
    ignored: ['**/node_modules', '**/*.py'],
    aggregateTimeout: 300,
    poll: 1000
  }
}
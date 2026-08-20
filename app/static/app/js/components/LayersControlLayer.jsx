import React from 'react';
import PropTypes from 'prop-types';
import '../css/LayersControlLayer.scss';
import Histogram from './Histogram';
import { Checkbox, ExpandButton } from './Toggle';
import Utils from '../classes/Utils';
import Workers from '../classes/Workers';
import ErrorMessage from './ErrorMessage';
import ExportAssetPanel from './ExportAssetPanel';
import ColorMaps from '../classes/ColorMaps';
import PluginsAPI from '../classes/plugins/API';
import $ from 'jquery';
import { _, interpolate } from '../classes/gettext';

export default class LayersControlLayer extends React.Component {
  static defaultProps = {
      layer: null,
      expanded: false,
      map: null,
      overlay: false,
      separator: false
  };
  static propTypes = {
    layer: PropTypes.object.isRequired,
    expanded: PropTypes.bool,
    map: PropTypes.object.isRequired,
    overlay: PropTypes.bool,
    separator: PropTypes.bool
  };

  constructor(props){
    super(props);

    this.map = props.map;

    const url = this.getLayerUrl();
    const params = Utils.queryParams({search: url.slice(url.indexOf("?"))});

    this.meta = props.layer[Symbol.for("meta")] || {};
    this.tmeta = props.layer[Symbol.for("tile-meta")] || {};

    // Compute download URL from metadata
    // (not ideal, but works)
    const mUrl = this.meta.metaUrl;
    const mUrlToDownload = [
        {url: "orthophoto/metadata", download: "orthophoto"},
        {url: "dsm/metadata", download: "dsm"},
        {url: "dtm/metadata", download: "dtm"}
    ];

    if (mUrl){
        for (let d of mUrlToDownload){
            const idx = mUrl.lastIndexOf(d.url);
            if (idx !== -1){
                this.asset = d.download;
                break;
            }
        }
    }

    this.state = {
        visible: this.map.hasLayer(props.layer),
        expanded: props.expanded,
        colorMap: params.color_map || "",
        formula: params.formula || "",
        bands: params.bands || "",
        hillshade: params.hillshade || "",
        histogramLoading: false,
        exportLoading: false,
        side: false,
        error: "",
        lazyLoading: false,
    };
    this.rescale = params.rescale || "";
  }

  getLayerUrl = () => {
      return this.props.layer._url || "";
  }

  componentDidMount(){
    PluginsAPI.Map.onMapTypeChanged(this.handleMapTypeChange);
    PluginsAPI.Map.onSideBySideChanged(this.handleSideBySideChange);
  }

  isLayerWithSameTaskIdVisible = () => {
    if (!this.meta.task) return true;

    const taskId = this.meta.task.id;
    for (let layer of Object.values(this.props.map._layers)){
        if (!layer[Symbol.for("meta")] || !layer.isHidden) continue;
        const meta = layer[Symbol.for("meta")];
        if (meta.task.id === taskId && 
            this.props.map.hasLayer(layer) && 
            !layer.isHidden()){
            return true;
        }
    }
    return false;
  }

  handleMapTypeChange = (type, autoExpand) => {
    if (this.meta.type !== undefined){
        const visible = this.meta.type === type && (autoExpand || this.isLayerWithSameTaskIdVisible());
        const expanded = visible && autoExpand;
        this.setState({visible, expanded});
    }
  }

  handleSideBySideChange = (layer, side) => {
    // Toggle this layer's side off if it was previously sided
    // when another layer is set to side
    if (this.props.layer !== layer && this.state.side && side){
        setTimeout(() => {
            let visible = this.state.visible;
            if (this.wasInvisibleOnSideClick){
                visible = false;
                this.wasInvisibleOnSideClick = false;
            }
    
            this.setState({ side: false, visible });
            PluginsAPI.Map.sideBySideChanged(this.props.layer, false);
        }, 0);
    }
  }

  componentDidUpdate(prevProps, prevState){
    const { layer } = this.props;

    if (prevState.visible !== this.state.visible){
        if (this.state.visible){
            if (layer.lazyLoad && !layer.lazyLoaded && !this.state.lazyLoading){
                this.setState({lazyLoading: true});
                layer.lazyLoad((err) => {
                    if (!err) layer.lazyLoaded = true;
                    this.setState({lazyLoading: false});
                });
            }

            if (layer.show) layer.show(); 
            else if (!this.map.hasLayer(layer)) layer.addTo(this.map);
        }else{
            if (layer.hide) layer.hide();
            else this.map.removeLayer(layer);
        }
    }

    if (prevState.hillshade !== this.state.hillshade){
        this.updateLayer();
    }

    if (prevState.formula !== this.state.formula ||
        prevState.bands !== this.state.bands){
        this.updateHistogram();
    }

    if (prevProps.expanded !== this.props.expanded){
        this.setState({expanded: this.props.expanded});
    }
  }

  componentWillUnmount(){
    if (this.updateHistogramReq){
        this.updateHistogramReq.abort();
        this.updateHistogramReq = null;
    }

    if (this.exportReq){
        this.exportReq.abort();
        this.exportReq = null;
    }

    PluginsAPI.Map.offSideBySideChanged(this.handleSideBySideChange);
    PluginsAPI.Map.offMapTypeChanged(this.handleMapTypeChange);
  }

  handleZoomToClick = () => {
    const { layer } = this.props;

    const bounds = layer.options.bounds !== undefined ? 
                   layer.options.bounds :
                   layer.getBounds();
    this.map.fitBounds(bounds);

    if (layer.getPopup()) layer.openPopup();
  }

  handleSideClick = () => {
    let { side, visible } = this.state;

    if (!side){
        side = true;
        if (!visible){
            visible = true;
            this.wasInvisibleOnSideClick = true;
        }
    }else{
        side = false;
        if (this.wasInvisibleOnSideClick){
            visible = false;
            this.wasInvisibleOnSideClick = false;
        }
    }

    this.setState({ side, visible });
    PluginsAPI.Map.sideBySideChanged(this.props.layer, side);
  }

  sideIcon = () => {
    if (!this.state.side) return "fa-divide fa-rotate-90";
    else return "fa-chevron-right";
  }

  handleLayerClick = () => {
    if (this.props.overlay){
        this.setState({visible: !this.state.visible});
    }else{
        this.setState({expanded: !this.state.expanded});
    }
  }

  handleSelectColor = e => {
    this.setState({colorMap: e.target.value});
  }

  handleSelectHillshade = e => {
    this.setState({hillshade: e.target.value});
  }

  handleSelectFormula = e => {
    let bands = this.state.bands;

    // Check if bands need to be switched
    const algo = this.getAlgorithm(e.target.value);
    if (algo && algo['filters'].indexOf(bands) === -1 && bands !== "auto") bands = algo['filters'][0]; // Pick first

    this.setState({formula: e.target.value, bands});
  }

  getAlgorithm = id => {
    const { algorithms } = this.tmeta;
    if (!id) return null;
    if (!algorithms) return null;

    for (let i in algorithms){
        const algo = algorithms[i];
        if (algo['id'] === id){
            return algo;
        }
    }
  }

  handleSelectBands = e => {
      this.setState({bands: e.target.value});
  }

  updateHistogram = () => {
    if (this.updateHistogramReq){
        this.updateHistogramReq.abort();
        this.updateHistogramReq = null;
    }

    this.setState({histogramLoading: true});
    this.updateHistogramReq = $.getJSON(Utils.buildUrlWithQuery(this.meta.metaUrl, this.getLayerParams()))
        .done(mres => {
            ColorMaps.decode(mres.color_maps);
            this.tmeta = this.props.layer[Symbol.for("tile-meta")] = mres;
            
            // Update rescale values
            const { statistics } = this.tmeta;
            if (statistics && statistics["1"]){
                let min = Infinity;
                let max = -Infinity;

                for (let b in statistics){
                    min = Math.min(min, statistics[b]["percentiles"][0]);
                    max = Math.max(max, statistics[b]["percentiles"][1]);
                }
                this.rescale = `${min},${max}`;
            }

            this.updateLayer();
        })
        .fail(err => console.error)
        .always(() => {
            this.setState({histogramLoading: false});
        });
  }

  getLayerParams = () => {
    const { colorMap,
        formula,
        bands,
        hillshade } = this.state;
    
    return {
        color_map: colorMap,
        formula,
        bands,
        hillshade,
        rescale: this.rescale,
        size: 512,
        crop: 1
    };
  }
  
  updateLayer = () => {
      if (this.updateTimer){
          clearTimeout(this.updateTimer);
          this.updateTimer = null;
      }

      this.updateTimer = setTimeout(() => {
        const url = this.getLayerUrl();
        const { layer } = this.props;
        const newUrl = Utils.buildUrlWithQuery(url, this.getLayerParams());

        layer.setUrl(newUrl, true);
            
        // Hack to get leaflet to actually redraw tiles :/
        layer._removeAllTiles();
        setTimeout(() => {
            layer.redraw();
        }, 1);
    }, 200);
  }

  handleHistogramUpdate = e => {
    this.rescale = `${e.min},${e.max}`;
    this.updateLayer();
  }

  handleExport = e => {
      const { formula } = this.state;
      const { tmeta } = this;
      const { algorithms } = tmeta;
      
      // Plant health needs to be exported
      if (formula !== "" && algorithms){
        this.setState({exportLoading: true, error: ""});
        
        this.exportReq = $.ajax({
                type: 'POST',
                url: `/api/projects/${this.meta.task.project}/tasks/${this.meta.task.id}/orthophoto/export`,
                data: this.getLayerParams()
            }).done(result => {
                if (result.celery_task_id){
                    Workers.waitForCompletion(result.celery_task_id, error => {
                        if (error) this.setState({exportLoading: false, error});
                        else{
                            this.setState({exportLoading: false});
                            Workers.downloadFile(result.celery_task_id, "odm_orthophoto_" + encodeURIComponent(this.state.formula) + ".tif");
                        }
                    });
                }else if (result.error){
                    this.setState({exportLoading: false, error: result.error});
                }else{
                    this.setState({exportLoading: false, error: interpolate(_("Invalid JSON response: %(error)s"), {error: JSON.stringify(result)})});
                }
            }).fail(error => {
                this.setState({exportLoading: false, error: JSON.stringify(error)});
            });
      }else{
          // Simple download
          window.location.href = this.downloadFileUrl;
      }
  }

  render(){
    const { colorMap, bands, hillshade, formula, histogramLoading, exportLoading, lazyLoading } = this.state;
    const { meta, tmeta } = this;
    const { color_maps, algorithms, auto_bands } = tmeta;
    const algo = this.getAlgorithm(formula);

    let cmapValues = null;
    if (colorMap){
        cmapValues = (color_maps.find(c => c.key === colorMap) || {}).decoded_color_map;
    }

    let hmin = null;
    let hmax = null;
    if (this.rescale){
        let parts = decodeURIComponent(this.rescale).split(",");
        if (parts.length === 2 && parts[0] && parts[1]){
            hmin = parseFloat(parts[0]);
            hmax = parseFloat(parts[1]);
        }
    }

    return (<div className="layers-control-layer">
        <div className="layer-control-title">
            {!this.props.overlay ? <ExpandButton bind={[this, 'expanded']} className="expand-layer" /> : <div className="paddingSpace"></div>}<Checkbox bind={[this, 'visible']} bindLoading={[this, 'lazyLoading']}/>
            <a title={meta.name} className="layer-label" href="javascript:void(0);" onClick={this.handleLayerClick}><i className={"layer-icon " + (meta.icon || "fa fa-vector-square fa-fw")}></i><div className="layer-title">{meta.name}</div></a> {meta.raster ? <a className="layer-action" href="javascript:void(0)" onClick={this.handleSideClick}><i title={_("Side By Side")} className={"fa fa-fw " + this.sideIcon()}></i></a> : ""}<a className="layer-action" href="javascript:void(0)" onClick={this.handleZoomToClick}><i title={_("Zoom To")} className="fa fa-expand"></i></a>
        </div>

        {this.state.expanded ? 
        <div className="layer-expanded">
            <Histogram width={274}
                        loading={histogramLoading}
                        statistics={tmeta.statistics}
                        unitForward={meta.unitForward}
                        unitBackward={meta.unitBackward}
                        colorMap={cmapValues}
                        min={hmin}
                        max={hmax}
                        onUpdate={this.handleHistogramUpdate} />

            <ErrorMessage bind={[this, "error"]} />

            {formula !== "" && algorithms ? 
            <div className="row form-group form-inline">
                <label className="col-sm-3 control-label">{_("Algorithm:")}</label>
                <div className="col-sm-9 ">
                    {histogramLoading ? 
                    <i className="fa fa-circle-notch fa-spin fa-fw" /> :
                    <select title={algo.help + '\n' + algo.expr} className="form-control" value={formula} onChange={this.handleSelectFormula}>
                        {algorithms.map(a => <option key={a.id} value={a.id} title={a.help + "\n" + a.expr}>{a.id}</option>)}
                    </select>}
                </div>
            </div> : ""}

            {bands !== "" && algo ? 
            <div className="row form-group form-inline">
                <label className="col-sm-3 control-label">{_("Bands:")}</label>
                <div className="col-sm-9 ">
                    {histogramLoading ? 
                    <i className="fa fa-circle-notch fa-spin fa-fw" /> :
                    [<select key="sel" className="form-control" value={bands} onChange={this.handleSelectBands} title={auto_bands.filter !== "" && bands == "auto" ? auto_bands.filter : ""}>
                        <option key="auto" value="auto">{_("Automatic")}</option>
                        {algo.filters.map(f => <option key={f} value={f}>{f}</option>)}
                    </select>,
                    bands == "auto" && !auto_bands.match ? 
                    <i key="ico" style={{marginLeft: '4px'}} title={interpolate(_("Not every band for %(name)s could be automatically identified."), {name: algo.id}) + "\n" + _("Your sensor might not have the proper bands for using this algorithm.")} className="fa fa-exclamation-circle info-button"></i>
                    : ""]}
                </div>
            </div> : ""}

            {colorMap && color_maps.length ? 
            <div className="row form-group form-inline">
                <label className="col-sm-3 control-label">{_("Color:")}</label>
                <div className="col-sm-9 ">
                    {histogramLoading ? 
                    <i className="fa fa-circle-notch fa-spin fa-fw" /> :
                    <select className="form-control" value={colorMap} onChange={this.handleSelectColor}>
                        {color_maps.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
                    </select>}
                </div>
            </div> : ""}

            {hillshade !== "" ? 
            <div className="row form-group form-inline">
                <label className="col-sm-3 control-label">{_("Shading:")}</label>
                <div className="col-sm-9 ">
                    <select className="form-control" value={hillshade} onChange={this.handleSelectHillshade}>
                        <option value="0">{_("None")}</option>
                        <option value="6">{_("Normal")}</option>
                        <option value="18">{_("Extruded")}</option>
                    </select>
                </div>
            </div> : ""}

            <ExportAssetPanel task={meta.task} 
                            asset={this.asset} 
                            exportParams={this.getLayerParams} 
                            dropUp />
            
            {this.props.separator ? <hr className="layer-separator" /> : ""}
        </div> : ""}
    </div>);

   }
}
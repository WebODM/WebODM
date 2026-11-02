import React from 'react';
import PropTypes from 'prop-types';
import L from 'leaflet';
import './RealignPanel.scss';
import ErrorMessage from 'webodm/components/ErrorMessage';
import Workers from 'webodm/classes/Workers';
import { _ } from 'webodm/classes/gettext';
import { fitSimilarity, applySimilarity } from './similarity';

const RASTER_TYPES = ['orthophoto', 'dsm', 'dtm'];
const SEMI_OPACITY = 0.5;

// Texto por causa de bloqueo de la corrección de nube (003-realign-pointcloud, US2, SC-009).
const POINTCLOUD_REASON_TEXT = {
  no_pointcloud: () => _("Esta tarea no tiene nube de puntos para corregir."),
  not_applied: () => _("Aplica primero la realineación (no solo la previsualización) para poder generar la nube corregida."),
  scale_enabled: () => _('La corrección de nube solo está disponible en modo rígido. Destilda "Usar escala", vuelve a Aplicar y repite la generación.'),
  already_running: () => _("Ya hay una generación de nube en curso para esta tarea."),
  pdal_missing: () => _("No se encontró PDAL en el servidor: no se puede generar la nube corregida."),
};

function fmtBytes(n){
  if (n === null || n === undefined || isNaN(n)) return "—";
  const units = ['B', 'KB', 'MB', 'GB'];
  let v = n, i = 0;
  while (v >= 1024 && i < units.length - 1){ v /= 1024; i++; }
  return `${v.toFixed(1)} ${units[i]}`;
}

function layerMeta(layer){
  return layer[Symbol.for('meta')] || layer.meta || {};
}

export default class RealignPanel extends React.Component {
  static propTypes = {
    onClose: PropTypes.func.isRequired,
    tasks: PropTypes.array.isRequired,
    tiles: PropTypes.array.isRequired,
    isShowed: PropTypes.bool.isRequired,
    map: PropTypes.object.isRequired
  }

  constructor(props){
    super(props);

    this.state = {
        checkingAvailability: true,
        permanentError: "",
        error: "",
        products: [],
        points: [],          // [{id, source:{lat,lng}, target:{lat,lng}, residual}]
        transform: null,     // {scale, rotationDeg, rmse, degenerate, n}
        useScale: true,      // false = transformación rígida (traslación+rotación, sin escala)
        captureMode: 'idle', // 'idle' | 'source' | 'target'
        applied: false,
        busy: false,
        currentCeleryTaskId: null,
        applyProgress: null,     // {status, progress} mientras se aplica
        canceling: false,        // cancelación pedida, esperando a que el servidor la confirme
        pointcloud: null,        // {status, stale, available, eligible, ineligible_reason, ...}
        pointcloudProgress: null, // {status, progress} mientras status === 'running'
        cancelingPointCloud: false, // descarte pedido, esperando confirmación del servidor
        task: props.tasks[0] || null
    };

    this._markers = {};        // id -> {source, target, line}
    this._pending = null;      // {latlng, marker} durante la captura del destino
    this._redirected = new Map(); // capa core -> URL de tiles original (mientras muestra los corregidos)
    this._fit = null;
    this._active = false;
    this._nextId = 1;
    this._origOpacity = null;
    this._applyToken = 0;      // invalida callbacks de apply obsoletos (revert/editar durante apply)
  }

  taskId = () => this.state.task.id;
  apiBase = () => `/api/plugins/realign/task/${this.taskId()}/realign`;

  componentDidMount(){
    // El estado se carga al montar (no al abrir el panel): si hay una realineación aplicada,
    // la vista corregida se restaura aunque el panel nunca se abra (recargas de página incluidas).
    this.loadingReq = $.getJSON(`${this.apiBase()}/state`)
      .done(res => {
        if (!res.products || res.products.length === 0){
          this.setState({permanentError: _("Esta tarea no tiene productos ráster 2D (ortofoto, DSM o DTM) para realinear.")});
        }else{
          this.setState({products: res.products});
          this.restoreState(res, () => {
            if (this.state.applied) this.showCorrected();
            // Reanudar el sondeo si había una generación de nube en curso al recargar (FR-011).
            const pc = this.state.pointcloud;
            if (pc && pc.status === 'running' && pc.celery_task_id) this.watchPointCloud(pc.celery_task_id);
          });
        }
      })
      .fail(() => this.setState({permanentError: _("No se pudo obtener el estado de la tarea. ¿Estás conectado a internet?")}))
      .always(() => { this.setState({checkingAvailability: false}); this.loadingReq = null; });

    // El core crea/recrea sus capas ráster en cualquier momento (carga inicial asíncrona,
    // re-render de loadImageryLayers, checkbox de la barra de capas): mientras haya una
    // corrección aplicada, cada capa original que aparezca se intercambia por la corregida.
    this._onLayerAdd = (e) => {
      if (!this.state.applied || !e.layer) return;
      const m = layerMeta(e.layer);
      if (RASTER_TYPES.indexOf(m.type) !== -1){
        setTimeout(() => { if (this.state.applied) this.redirectCoreLayer(e.layer); }, 0);
      }
    };
    this.props.map.on('layeradd', this._onLayerAdd);
  }

  componentDidUpdate(){
    const { isShowed } = this.props;

    if (isShowed && !this._active && !this.state.checkingAvailability && !this.state.permanentError){
      this.activate();
    }else if (!isShowed && this._active){
      this.deactivate();
    }
  }

  componentWillUnmount(){
    if (this._active) this.deactivate();
    if (this._onLayerAdd){ this.props.map.off('layeradd', this._onLayerAdd); this._onLayerAdd = null; }
    if (this.loadingReq){ this.loadingReq.abort(); this.loadingReq = null; }
  }

  // --- Restaurar estado persistido (FR-013) --------------------------------

  restoreState = (res, cb) => {
    // 'applying' (job interrumpido) se trata como previsualización recuperable. 'applied' solo
    // cuenta si los corregidos siguen en disco: si se borraron (a mano, o perdidos al actualizar
    // desde una versión que los guardaba dentro del plugin), redirigir las capas dejaría el mapa
    // en blanco; así el panel vuelve a ofrecer Aplicar.
    const applied = res.state === 'applied' && !!res.corrected_available;
    // Estados persistidos antes de esta capacidad no tienen use_scale: se interpretan como true
    // (preserva el comportamiento con el que se crearon — FR-020, D9).
    const useScale = (res.transform && typeof res.transform.use_scale === 'boolean') ? res.transform.use_scale : true;
    const pointcloud = res.pointcloud || null;
    // Si la última aplicación falló, el motivo lo guarda el servidor: al recargar la página el
    // resultado de Celery ya no está y sin esto el panel volvía a previsualización sin explicar
    // por qué no hay productos corregidos.
    const error = res.state === 'error' && res.error ? res.error : "";
    if (Array.isArray(res.points) && res.points.length){
      const points = res.points.map(p => ({
        id: (typeof p.id === 'number' ? p.id : this._nextId++),
        source: p.source, target: p.target, residual: p.residual_m
      }));
      this._nextId = Math.max(this._nextId, ...points.map(p => p.id)) + 1;
      this.setState({points, applied, useScale, pointcloud, error}, cb);
    }else{
      this.setState({applied, useScale, pointcloud, error}, cb);
    }
  }

  // --- Activación / desactivación ------------------------------------------

  activate = () => {
    this._active = true;
    this.redrawMarkers();
    if (this.state.applied){
      this.showCorrected();
    }else{
      this.setSemiTransparency(true);
      this.recompute();
    }
  }

  deactivate = () => {
    this.stopCapture();
    this.setSemiTransparency(false);
    this.removeAllMarkers();
    // Cerrar el panel NO revierte la vista: si la corrección está aplicada (o aplicándose,
    // el polling sigue y hará la redirección al terminar), los tiles corregidos persisten.
    // Solo en previsualización pura se descarta todo lo visual.
    if (!this.state.applied && !this.state.busy && !this.state.currentCeleryTaskId){
      this._applyToken++;
      this.restoreCoreLayers();
    }
    this._active = false;
  }

  // --- Capas ráster --------------------------------------------------------

  // props.tiles son descriptores planos ({url, type, meta}) — el core clona meta antes de
  // asignarle type, así que las capas Leaflet reales solo se encuentran iterando el mapa
  // (llevan Symbol.for("meta") con type, asignado en Map.jsx: loadImageryLayers).
  getRasterLayers = () => {
    const layers = [];
    this.props.map.eachLayer(l => {
      const m = layerMeta(l);
      if (RASTER_TYPES.indexOf(m.type) !== -1) layers.push(l);
    });
    return layers;
  }

  getOrthophotoLayer = () => this.getRasterLayers().find(l => layerMeta(l).type === 'orthophoto');

  setSemiTransparency = (on) => {
    const layer = this.getOrthophotoLayer();
    if (!layer) return;
    if (on){
      if (this._origOpacity === null) this._origOpacity = (typeof layer.options.opacity === 'number') ? layer.options.opacity : 1;
      layer.setOpacity(SEMI_OPACITY);
    }else if (this._origOpacity !== null){
      layer.setOpacity(this._origOpacity);
      this._origOpacity = null;
    }
  }

  // --- Capas corregidas (tiles servidos por el plugin) ---------------------

  // Redirige la URL de tiles de una capa ráster del core hacia los tiles corregidos del
  // plugin. La capa del core queda intacta en el mapa (panel de capas, opacidad, side-by-side
  // siguen funcionando con normalidad); solo cambia de dónde vienen sus imágenes. Esto evita
  // remover/añadir capas, que rompe invariantes del gestor de capas del core.
  redirectCoreLayer = (layer) => {
    if (this._redirected.has(layer) || typeof layer.setUrl !== 'function') return;
    const type = layerMeta(layer).type;
    this._redirected.set(layer, layer._url);
    // Conservar los query params de la capa del core — en particular size=512, el esquema
    // retina/z+1 que el endpoint de tiles compensa server-side igual que el tiler del core.
    const qIdx = layer._url.indexOf('?');
    const sep = (qIdx !== -1) ? `?${layer._url.slice(qIdx + 1)}&` : '?';
    layer.setUrl(`${this.apiBase()}/tiles/${type}/{z}/{x}/{y}.png${sep}v=${Date.now()}`);
  }

  showCorrected = () => {
    this.setSemiTransparency(false);
    this.getRasterLayers().forEach(this.redirectCoreLayer);
  }

  restoreCoreLayers = () => {
    this._redirected.forEach((url, layer) => layer.setUrl(url));
    this._redirected.clear();
  }

  // Vuelve de 'aplicado' a 'previsualización' al empezar a editar (permite rehacer).
  exitApplied = () => {
    this._applyToken++;
    if (this.state.currentCeleryTaskId) Workers.cancel(this.state.currentCeleryTaskId);
    const wasApplied = this.state.applied || this._redirected.size > 0;
    if (wasApplied){
      this.restoreCoreLayers();
      this.setSemiTransparency(true);
    }
    if (this.state.applied || this.state.busy || this.state.currentCeleryTaskId){
      this.setState({applied: false, busy: false, currentCeleryTaskId: null});
    }
  }

  // --- Captura de pares ----------------------------------------------------

  makeIcon = (kind) => L.divIcon({className: `realign-marker realign-marker-${kind}`, iconSize: [14, 14]});

  handleAddPair = () => {
    this.exitApplied();
    if (this.state.captureMode !== 'idle'){ this.cancelCapture(); return; }
    this.setState({captureMode: 'source', error: ""});
    this.props.map.on('click', this.handleMapClick);
    this.props.map.getContainer().style.cursor = 'crosshair';
  }

  handleMapClick = (e) => {
    if (this.state.captureMode === 'source'){
      const marker = L.marker(e.latlng, {icon: this.makeIcon('source')}).addTo(this.props.map);
      this._pending = {latlng: e.latlng, marker};
      this.setState({captureMode: 'target'});
    }else if (this.state.captureMode === 'target'){
      const id = this._nextId++;
      const point = {id, source: {lat: this._pending.latlng.lat, lng: this._pending.latlng.lng},
                          target: {lat: e.latlng.lat, lng: e.latlng.lng}, residual: null};
      this.props.map.removeLayer(this._pending.marker);
      this._pending = null;
      this.stopCapture();
      this.setState({points: [...this.state.points, point]}, () => {
        this.drawMarkersForPoint(point);
        this.recompute();
        this.persistState();
      });
    }
  }

  cancelCapture = () => {
    if (this._pending){ this.props.map.removeLayer(this._pending.marker); this._pending = null; }
    this.stopCapture();
  }

  stopCapture = () => {
    this.props.map.off('click', this.handleMapClick);
    this.props.map.getContainer().style.cursor = '';
    if (this.state.captureMode !== 'idle') this.setState({captureMode: 'idle'});
  }

  // --- Marcadores ----------------------------------------------------------

  drawMarkersForPoint = (point) => {
    const { map } = this.props;
    const source = L.marker(point.source, {icon: this.makeIcon('source'), draggable: true}).addTo(map);
    const target = L.marker(point.target, {icon: this.makeIcon('target'), draggable: true}).addTo(map);
    const line = L.polyline([point.source, point.target], {color: '#ff9800', weight: 2, dashArray: '4,3'}).addTo(map);

    source.on('dragstart', this.exitApplied);
    target.on('dragstart', this.exitApplied);
    source.on('drag', () => this.handleMarkerDrag(point.id, 'source', source.getLatLng(), false));
    target.on('drag', () => this.handleMarkerDrag(point.id, 'target', target.getLatLng(), false));
    source.on('dragend', () => this.handleMarkerDrag(point.id, 'source', source.getLatLng(), true));
    target.on('dragend', () => this.handleMarkerDrag(point.id, 'target', target.getLatLng(), true));

    this._markers[point.id] = {source, target, line};
  }

  handleMarkerDrag = (id, kind, latlng, persist) => {
    const points = this.state.points.map(p => p.id === id ? {...p, [kind]: {lat: latlng.lat, lng: latlng.lng}} : p);
    const m = this._markers[id];
    if (m) m.line.setLatLngs([kind === 'source' ? latlng : m.source.getLatLng(),
                              kind === 'target' ? latlng : m.target.getLatLng()]);
    this.setState({points}, () => { this.recompute(); if (persist) this.persistState(); });
  }

  removeMarkersForPoint = (id) => {
    const m = this._markers[id];
    if (m){ this.props.map.removeLayer(m.source); this.props.map.removeLayer(m.target); this.props.map.removeLayer(m.line); delete this._markers[id]; }
  }

  removeAllMarkers = () => {
    Object.keys(this._markers).forEach(id => this.removeMarkersForPoint(parseInt(id, 10)));
    if (this._pending){ this.props.map.removeLayer(this._pending.marker); this._pending = null; }
  }

  redrawMarkers = () => { this.removeAllMarkers(); this.state.points.forEach(p => this.drawMarkersForPoint(p)); }

  handleRemovePoint = (id) => {
    this.exitApplied();
    this.removeMarkersForPoint(id);
    this.setState({points: this.state.points.filter(p => p.id !== id)}, () => { this.recompute(); this.persistState(); });
  }

  handleClearAll = () => {
    this.exitApplied();
    this.removeAllMarkers();
    this.setState({points: [], transform: null}, () => { this._fit = null; this.persistState(); });
  }

  handleToggleScale = (e) => {
    const useScale = e.target.checked;
    this.exitApplied();
    this.setState({useScale}, () => { this.recompute(); this.persistState(); });
  }

  // --- Recalculo -----------------------------------------------------------

  serializePoints = () => this.state.points.map(p => ({id: p.id, source: p.source, target: p.target, enabled: true}));

  recompute = () => {
    const { map } = this.props;
    const { points } = this.state;

    if (points.length === 0){ this._fit = null; this.setState({transform: null}); return; }

    const crs = map.options.crs;
    const pairs = points.map(p => {
      const s = crs.project(L.latLng(p.source.lat, p.source.lng));
      const t = crs.project(L.latLng(p.target.lat, p.target.lng));
      return {sx: s.x, sy: s.y, tx: t.x, ty: t.y};
    });

    const fit = fitSimilarity(pairs, this.state.useScale);
    this._fit = fit;

    let rmseM = null;
    const withResiduals = points.map((p, i) => {
      if (!fit.ok || fit.degenerate) return {...p, residual: null};
      const s = pairs[i];
      const q = applySimilarity(fit, s.sx, s.sy);
      const residual = map.distance(crs.unproject(L.point(q.x, q.y)), L.latLng(p.target.lat, p.target.lng));
      return {...p, residual};
    });
    if (fit.ok && !fit.degenerate){
      const sumSq = withResiduals.reduce((acc, p) => acc + (p.residual || 0) * (p.residual || 0), 0);
      rmseM = Math.sqrt(sumSq / withResiduals.length);
    }

    this.setState({points: withResiduals,
      transform: {scale: fit.scale, rotationDeg: fit.rotationDeg, rmse: rmseM, degenerate: fit.degenerate, n: fit.n}});
  }

  // --- Persistencia / Aplicar / Revertir -----------------------------------

  persistState = () => {
    // Requiere change_project; para usuarios de solo lectura el 404 se ignora en silencio.
    return $.ajax({type: 'PUT', url: `${this.apiBase()}/state`,
                   data: JSON.stringify({points: this.serializePoints(), use_scale: this.state.useScale}),
                   contentType: 'application/json'})
            // Editar puntos o el modo de escala vuelve la realineación a 'previsualización':
            // el servidor ya recalcula `pointcloud.eligible`/`stale` en la misma respuesta
            // (deja de ofrecerse una nube generada con un ajuste que ya no es el vigente — FR-012).
            .done(res => { if (res.pointcloud) this.setState({pointcloud: res.pointcloud}); })
            .fail(() => {});
  }

  handleApply = () => {
    if (this.state.busy) return;
    const token = ++this._applyToken;
    this.setState({busy: true, error: "", applyProgress: null, canceling: false});
    $.ajax({type: 'POST', url: `${this.apiBase()}/apply`,
            data: JSON.stringify({points: this.serializePoints(), use_scale: this.state.useScale}),
            contentType: 'application/json'})
      .done(res => {
        if (token !== this._applyToken) return; // acción posterior invalidó este apply
        if (res.celery_task_id){
          this.setState({currentCeleryTaskId: res.celery_task_id});
          Workers.waitForCompletion(res.celery_task_id, error => {
            if (token !== this._applyToken) return; // revert/editar mientras corría → ignorar
            if (error){ this.setState({busy: false, error, currentCeleryTaskId: null, applyProgress: null}); }
            else {
              this.setState({busy: false, applied: true, currentCeleryTaskId: null, applyProgress: null}, () => {
                this.showCorrected();
                // Aplicar cambia state -> 'applied', una de las condiciones de elegibilidad
                // de la nube de puntos (FR-005) — refrescar para reflejarlo.
                this.refreshPointCloudState();
              });
            }
          },
          // El pipeline reporta qué producto está corrigiendo y cuánto lleva: sin esto el
          // usuario solo veía un botón, sin saber si había algo en marcha.
          (statusText, progress) => {
            if (token === this._applyToken){
              this.setState({applyProgress: {status: statusText, progress}});
            }
          });
        }else{
          this.setState({busy: false, error: res.error || _("Respuesta inválida del servidor.")});
        }
      })
      .fail(xhr => { if (token === this._applyToken) this.setState({busy: false, error: this.errFromXhr(xhr)}); });
  }

  // Cancelar una aplicación en marcha. Se para por los dos lados: `Workers.cancel` corta el
  // sondeo aquí y `persistState` hace que el backend aborte la tarea (el pipeline consulta la
  // cancelación entre productos y durante el remuestreo) y deje el estado en previsualización,
  // en vez de un 'applying' que ya no corresponde a nada.
  handleCancelApply = () => {
    if (this.state.canceling) return;
    const celeryTaskId = this.state.currentCeleryTaskId;
    this._applyToken++; // invalida el callback del apply en curso
    // El botón se queda en pantalla como "Cancelando…" hasta que el servidor confirma: parar el
    // remuestreo no es instantáneo y hacerlo desaparecer antes daría por hecho algo que aún no
    // ha ocurrido.
    this.setState({canceling: true});
    if (celeryTaskId) Workers.cancel(celeryTaskId);
    this.persistState().always(() => {
      this.setState({busy: false, canceling: false, currentCeleryTaskId: null,
                     applyProgress: null, error: ""});
    });
  }

  handleRevert = () => {
    if (this.state.busy) return;
    this._applyToken++;
    if (this.state.currentCeleryTaskId) Workers.cancel(this.state.currentCeleryTaskId);
    this.setState({busy: true, error: ""});
    $.ajax({type: 'POST', url: `${this.apiBase()}/revert`})
      .done(() => {
        this.restoreCoreLayers();
        this.setState({busy: false, applied: false, currentCeleryTaskId: null, applyProgress: null}, () => {
          this.setSemiTransparency(true);
          this.recompute();
          // Revertir descarta también la nube corregida en el servidor (FR-013) — refrescar.
          this.refreshPointCloudState();
        });
      })
      .fail(xhr => this.setState({busy: false, error: this.errFromXhr(xhr)}));
  }

  // --- Nube de puntos corregida (003-realign-pointcloud) --------------------

  refreshPointCloudState = () => {
    return $.getJSON(`${this.apiBase()}/state`)
      .done(res => this.setState({pointcloud: res.pointcloud || null}));
  }

  watchPointCloud = (celeryTaskId) => {
    this.setState({pointcloudProgress: null});
    // Se ignora el mensaje de error puntual del sondeo: el estado autoritativo (incluida la
    // causa de un fallo o cancelación) vive en el store del servidor (FR-014) y se recupera
    // siempre con un GET state fresco, en vez de confiar en el resultado transitorio de Celery.
    Workers.waitForCompletion(celeryTaskId, () => this.refreshPointCloudState(),
      (statusText, progress) => this.setState({pointcloudProgress: {status: statusText, progress}}));
  }

  handleGeneratePointCloud = () => {
    const pc = this.state.pointcloud;
    if (!pc || !pc.eligible) return;
    this.setState({pointcloud: {...pc, status: 'running', error: null}, pointcloudProgress: null});
    $.ajax({type: 'POST', url: `${this.apiBase()}/pointcloud`})
      .done(res => {
        if (res.celery_task_id){
          this.setState({pointcloud: {...this.state.pointcloud, status: 'running', celery_task_id: res.celery_task_id}});
          this.watchPointCloud(res.celery_task_id);
        }else{
          this.refreshPointCloudState();
        }
      })
      .fail(xhr => this.setState({pointcloud: {...this.state.pointcloud, status: 'error', error: this.errFromXhr(xhr)}}));
  }

  handleDiscardPointCloud = () => {
    if (this.state.cancelingPointCloud) return;
    // Igual que al cancelar la aplicación: el botón se queda visible como "Cancelando…" hasta
    // que el servidor confirma, en vez de dar por hecho algo que aún no ha terminado.
    this.setState({cancelingPointCloud: true});
    const done = () => this.refreshPointCloudState()
      .always(() => this.setState({cancelingPointCloud: false, pointcloudProgress: null}));
    $.ajax({type: 'DELETE', url: `${this.apiBase()}/pointcloud`})
      .done(done)
      .fail(done);
  }

  errFromXhr = (xhr) => {
    if (xhr && xhr.status === 404) return _("No tienes permiso para modificar esta tarea.");
    try { return JSON.parse(xhr.responseText).error || xhr.responseText; } catch(e){ return _("Error del servidor."); }
  }

  fmt = (v, digits = 2) => (v === null || v === undefined || isNaN(v)) ? "—" : Number(v).toFixed(digits);

  // --- Sección de nube de puntos (003-realign-pointcloud) -------------------

  renderPointCloudSection = () => {
    const { pointcloud, pointcloudProgress, cancelingPointCloud } = this.state;
    if (!pointcloud) return "";

    // FR-017: la tarea nunca va a tener nube en esta sesión — nota compacta, sin acción.
    if (pointcloud.status === 'absent' && pointcloud.ineligible_reason === 'no_pointcloud'){
      return (<div className="realign-pointcloud">
        <hr/>
        <div className="realign-note">{POINTCLOUD_REASON_TEXT.no_pointcloud()}</div>
      </div>);
    }

    let body;
    if (pointcloud.status === 'running'){
      const pct = pointcloudProgress ? Math.round(pointcloudProgress.progress) : null;
      // Mismo lenguaje que el de aplicar: progreso a la izquierda y un botón rojo con spinner a
      // la derecha. Las dos operaciones largas del panel se cancelan igual.
      body = (<div className="realign-running-row">
        <div className="realign-apply-progress">
          {(pointcloudProgress && pointcloudProgress.status) || _("Generando la nube corregida…")}
          {pct !== null ? ` (${pct}%)` : ""}
        </div>
        <button type="button" className="btn btn-sm btn-danger" disabled={cancelingPointCloud}
                onClick={this.handleDiscardPointCloud}>
          <i className="fa fa-circle-notch fa-spin" />{" "}
          {cancelingPointCloud ? _("Cancelando…") : _("Cancelar")}
        </button>
      </div>);
    }else if (pointcloud.status === 'ready' && pointcloud.available){
      body = (<div>
        <div>
          {_("Nube corregida lista")} ({fmtBytes(pointcloud.size_bytes)}
          {pointcloud.point_count ? `, ${pointcloud.point_count} ${_("puntos")}` : ""})
        </div>
        <a className="btn btn-sm btn-default" href={`${this.apiBase()}/pointcloud/download`}>
          <i className="fa fa-download" /> {_("Descargar nube corregida (.laz)")}
        </a>
        {" "}
        <a href="javascript:void(0);" onClick={this.handleDiscardPointCloud}>{_("Descartar")}</a>
      </div>);
    }else if (pointcloud.status === 'ready' && pointcloud.stale){
      body = (<div className="alert alert-warning">
        {_("El ajuste cambió desde que se generó esta nube: ya no corresponde a la corrección vigente.")}
        {pointcloud.eligible ?
          <div><a href="javascript:void(0);" onClick={this.handleGeneratePointCloud}>{_("Volver a generar")}</a></div> : ""}
      </div>);
    }else if (pointcloud.status === 'error'){
      body = (<div className="alert alert-warning">
        {pointcloud.error || _("No se pudo generar la nube corregida.")}
        {pointcloud.eligible ?
          <div><a href="javascript:void(0);" onClick={this.handleGeneratePointCloud}>{_("Reintentar")}</a></div> : ""}
      </div>);
    }else if (pointcloud.eligible){
      body = (<button type="button" className="btn btn-sm btn-default" onClick={this.handleGeneratePointCloud}>
        <i className="fa fa-cube" /> {_("Generar nube de puntos corregida")}
      </button>);
    }else{
      body = (<div className="realign-note">{(POINTCLOUD_REASON_TEXT[pointcloud.ineligible_reason] || (() => ""))()}</div>);
    }

    return (<div className="realign-pointcloud">
      <hr/>
      <div className="realign-pointcloud-title"><strong>{_("Nube de puntos")}</strong></div>
      {body}
      <div className="realign-note realign-pointcloud-disclaimer">
        {_("La corrección de nube solo afecta al archivo descargable; el visor 3D sigue mostrando la nube original.")}
      </div>
    </div>);
  }

  render(){
    const { checkingAvailability, permanentError, products, points, transform, useScale, captureMode, applied, busy, currentCeleryTaskId, applyProgress, canceling } = this.state;

    let content = "";
    if (checkingAvailability){
      content = (<span><i className="fa fa-circle-notch fa-spin"></i> {_("Cargando…")}</span>);
    }else if (permanentError){
      content = (<div className="alert alert-warning">{permanentError}</div>);
    }else{
      const capturing = captureMode !== 'idle';
      const degenerate = transform && transform.degenerate;
      const canApply = points.length >= 1 && transform && !degenerate && !busy;

      content = (<div>
        <ErrorMessage bind={[this, "error"]} />

        <p className="realign-help">
          {applied ? _("Realineación aplicada. Edita los puntos para rehacerla, o revierte al original.")
                   : _("Marca pares de puntos: primero un rasgo en la ortofoto, luego el mismo rasgo en el mapa base. La ortofoto se moverá al pulsar Aplicar.")}
        </p>

        <div className="row action-buttons">
          <div className="col-sm-12">
            <button type="button" className="btn btn-sm btn-primary" onClick={this.handleAddPair} disabled={busy}>
              <i className={capturing ? "fa fa-times" : "fa fa-plus"} />{" "}
              {captureMode === 'source' ? _("Haz clic en la ortofoto…")
                : captureMode === 'target' ? _("Ahora en el mapa base…")
                : _("Añadir par de puntos")}
            </button>
            {" "}
            {points.length > 0 ?
              <button type="button" className="btn btn-sm btn-secondary" onClick={this.handleClearAll} disabled={busy}>
                <i className="fa fa-trash" /> {_("Limpiar")}
              </button> : ""}
          </div>
        </div>

        {points.length > 0 ?
          <div className="realign-points-wrapper">
            <table className="table table-condensed realign-points">
              <thead><tr><th>#</th><th className="text-right">{_("Error (m)")}</th><th></th></tr></thead>
              <tbody>
                {points.map((p, i) => (
                  <tr key={p.id}>
                    <td>{i + 1}</td>
                    <td className="text-right">{this.fmt(p.residual)}</td>
                    <td className="text-right">
                      <a href="javascript:void(0);" title={_("Eliminar")} onClick={() => this.handleRemovePoint(p.id)}><i className="fa fa-times" /></a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div> : ""}

        <div className="row realign-scale-toggle">
          <div className="col-sm-12">
            <label>
              <input type="checkbox" checked={useScale} onChange={this.handleToggleScale} disabled={busy} />{" "}
              {_("Usar escala")}
            </label>
          </div>
        </div>

        {transform && !degenerate ?
          <div className="realign-summary">
            <div><strong>{_("RMSE:")}</strong> {this.fmt(transform.rmse)} m</div>
            <div><strong>{_("Escala:")}</strong> {this.fmt(transform.scale, 4)}</div>
            <div><strong>{_("Rotación:")}</strong> {this.fmt(transform.rotationDeg, 3)}°</div>
            {transform.n < 2 ? <div className="realign-note">{_("Con 1 par solo se aplica traslación.")}</div> : ""}
          </div> : ""}

        {degenerate ?
          <div className="alert alert-warning">
            {_("Los puntos actuales no permiten calcular la transformación (coincidentes o insuficientes).")}
          </div> : ""}

        {/* Flex y no el grid del core: con `max-width: 320px` cada `col-sm-6` deja 160 px, donde
            no caben dos descargas, y las que sobraban se descolgaban del botón de la derecha. */}
        <div className="realign-actions">
          <div className="realign-actions-secondary">
            {busy && currentCeleryTaskId ?
              <div className="realign-apply-progress">
                {(applyProgress && applyProgress.status) || _("Aplicando…")}
                {applyProgress && applyProgress.progress ? ` (${Math.round(applyProgress.progress)}%)` : ""}
              </div>
            : applied ? products.map(p => (
              <a key={p} href={`${this.apiBase()}/download/${p}`}
                 className="btn btn-sm btn-default" title={_("Descargar corregido")}>
                <i className="fa fa-download" /> {p}
              </a>
            )) : ""}
          </div>
          <div className="realign-actions-primary">
            {/* Mientras se aplica, Aplicar y Revertir están deshabilitados: sin esta salida el
                usuario que se arrepiente no tiene ninguna, y el remuestreo sigue igual. */}
            {busy && currentCeleryTaskId ?
              // El spinner dice que hay trabajo en marcha; el texto, qué hace el botón.
              <button type="button" className="btn btn-sm btn-danger" onClick={this.handleCancelApply}
                      disabled={canceling}>
                <i className="fa fa-circle-notch fa-spin"/>{" "}
                {canceling ? _("Cancelando…") : _("Cancelar")}
              </button>
              : applied ?
              <button type="button" className="btn btn-sm btn-danger" onClick={this.handleRevert} disabled={busy}>
                {busy ? <i className="fa fa-spin fa-circle-notch"/> : <i className="fa fa-undo"/>} {_("Revertir")}
              </button>
              :
              <button type="button" className="btn btn-sm btn-success" onClick={this.handleApply} disabled={!canApply}>
                {busy ? <i className="fa fa-spin fa-circle-notch"/> : <i className="fa fa-check"/>} {_("Aplicar")}
              </button>}
          </div>
        </div>

        {this.renderPointCloudSection()}
      </div>);
    }

    return (<div className="realign-panel">
      <span className="close-button" onClick={this.props.onClose}/>
      <div className="title">{_("Realign")}</div>
      <hr/>
      {content}
    </div>);
  }
}

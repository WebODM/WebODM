import '../css/NewTaskPanel.scss';
import React from 'react';
import EditTaskForm from './EditTaskForm';
import PropTypes from 'prop-types';
import Storage from '../classes/Storage';
import ResizeModes from '../classes/ResizeModes';
import MapPreview from './MapPreview';
import update from 'immutability-helper';
import PluginsAPI from '../classes/plugins/API';
import statusCodes from '../classes/StatusCodes';
import Gcp from '../classes/Gcp';
import { _, interpolate } from '../classes/gettext';

class NewTaskPanel extends React.Component {
  static defaultProps = {
    filesCount: 0,
    showResize: false,
    showAlign: false,
    projectId: null,
    basemaps: []
  };

  static propTypes = {
      onSave: PropTypes.func.isRequired,
      onCancel: PropTypes.func,
      filesCount: PropTypes.number,
      showResize: PropTypes.bool,
      showAlign: PropTypes.bool,
      getFiles: PropTypes.func,
      projectId: PropTypes.number,
      suggestedTaskName: PropTypes.oneOfType([PropTypes.string, PropTypes.func]),
      basemaps: PropTypes.array
  };

  constructor(props){
    super(props);

    this.state = {
      editTaskFormLoaded: false,
      resizeMode: Storage.getItem('resize_mode') === null ? ResizeModes.NO : ResizeModes.fromString(Storage.getItem('resize_mode')),
      resizeSize: parseInt(Storage.getItem('resize_size')) || 2048,
      alignTo: "auto",
      alignTasks: [], // loaded on mount if showAlign is true
      loadingAlignTasks: false,
      items: [], // Coming from plugins,
      taskInfo: {},
      inReview: false,
      loading: false,
      showMapPreview: false,
      dismissImageCountWarning: false,
      showMalformedGcpErrors: false,
    };

    this.save = this.save.bind(this);
    this.handleFormTaskLoaded = this.handleFormTaskLoaded.bind(this);
    this.getTaskInfo = this.getTaskInfo.bind(this);
    this.setResizeMode = this.setResizeMode.bind(this);
    this.handleResizeSizeChange = this.handleResizeSizeChange.bind(this);
    this.handleFormChanged = this.handleFormChanged.bind(this);
  }

  componentDidUpdate(prevProps, prevState){
    if (this.props.filesCount !== prevProps.filesCount && this.mapPreview){
      this.mapPreview.loadNewFiles();
    }
  }

  componentDidMount(){
    PluginsAPI.Dashboard.triggerAddNewTaskPanelItem({}, (item) => {
        if (!item) return;

        this.setState(update(this.state, {
            items: {$push: [item]}
        }));
    });
  }

  componentWillUnmount(){
    if (this.alignTasksRequest) this.alignTasksRequest.abort();
  }

  loadAlignTasks = (bbox) => {
    this.setState({alignTasks: [], alignTo: "auto", loadingAlignTasks: true});

    this.alignTasksRequest = 
      $.getJSON(`/api/projects/${this.props.projectId}/tasks/?ordering=-created_at&status=${statusCodes.COMPLETED}&available_assets=georeferenced_model.laz&bbox=${bbox.join(",")}`, tasks => {
        if (Array.isArray(tasks)){
          this.setState({loadingAlignTasks: false, alignTasks: tasks});
        }else{
          this.setState({loadingAlignTasks: false});
        }
      }).fail(() => {
        this.setState({loadingAlignTasks: false});
      });
  }

  save(e){
    if (!this.state.inReview){
      this.setState({inReview: true});
    }else{
      this.setState({inReview: false, loading: true});
      e.preventDefault();
      this.taskForm.saveLastPresetToStorage();
      Storage.setItem('resize_size', this.state.resizeSize);
      Storage.setItem('resize_mode', this.state.resizeMode);

      const taskInfo = this.getTaskInfo();
      if (taskInfo.selectedNode.key != "auto"){
        Storage.setItem('last_processing_node', taskInfo.selectedNode.id);
      }else{
        Storage.setItem('last_processing_node', '');
      }

      if (this.props.onSave) this.props.onSave(taskInfo);
    }
  }

  cancel = (e) => {
    if (this.state.inReview){
      this.setState({inReview: false});
    }else{
      if (this.props.onCancel){
        if (window.confirm(_("Are you sure you want to cancel?"))){
          this.props.onCancel();
        }
      }
    }
  }

  getTaskInfo(){
    return Object.assign(this.taskForm.getTaskInfo(), {
      resizeSize: this.state.resizeSize,
      resizeMode: this.state.resizeMode,
      alignTo: this.state.alignTo
    });
  }

  setResizeMode(v){
    return e => {
      this.setState({resizeMode: v});

      setTimeout(() => {
          this.handleFormChanged();
      }, 0);
    }
  }

  handleResizeSizeChange(e){
    // Remove all non-digit characters
    let n = parseInt(e.target.value.replace(/[^\d]*/g, ""));
    if (isNaN(n)) n = "";
    this.setState({resizeSize: n});
    
    setTimeout(() => {
        this.handleFormChanged();
    }, 0);
  }

  handleFormTaskLoaded(){
    this.setState({editTaskFormLoaded: true});
  }

  handleFormChanged(){
    this.setState({taskInfo: this.getTaskInfo()});
  }

  handleSuggestedTaskName = () => {
    return this.props.suggestedTaskName(() => {
      // Has GPS
      this.setState({showMapPreview: true});
    });
  }

  getCropPolygon = () => {
    if (!this.mapPreview) return null;
    return this.mapPreview.getCropPolygon();
  };

  getGcpFile = () => {
    if (!this.props.getFiles) return null;

    const files = this.props.getFiles();
    for (let i = 0; i < files.length; i++){
      const f = files[i];
      if (f.type.indexOf("text") === 0 && ["geo.txt", "image_groups.txt"].indexOf(f.name.toLowerCase()) === -1){
        if (!f._gcp){
          const reader = new FileReader();
          reader.onload = (e) => {
            if (e.target.result){
              const gcp = new Gcp(e.target.result);
              if (!gcp.valid()){
                this.setState({showMalformedGcpErrors: true});
              }
              f._gcp = gcp;
            }
          };
          reader.readAsText(f);
        }
        
        return f;
      }
    }
  }

  // [longitude, latitude] of each photo with a position, once the map has read them
  getPhotoPositions = () => {
    if (!this.mapPreview) return [];
    return this.mapPreview.exifData
      .filter(exif => exif.gps)
      .map(exif => [exif.gps.longitude, exif.gps.latitude]);
  };

  handlePolygonChange = () => {
    if (this.taskForm) this.taskForm.forceUpdate();
  }

  handleImagesBboxChange = (bbox) => {
    if (this.props.showAlign){
      this.loadAlignTasks(bbox);
    }
  }

  handleAlignToChanged = e => {
    this.setState({alignTo: e.target.value});
    if (this.mapPreview){
      if (e.target.value !== "auto"){
        this.mapPreview.setAlignmentPolygon(this.state.alignTasks.find(t => t.id === e.target.value));
      }else{
        this.mapPreview.setAlignmentPolygon(null);
      }
    }

    setTimeout(() => {
        this.handleFormChanged();
    }, 0);
  }

  render() {
    let filesCountOk = true;
    if (this.taskForm && !this.taskForm.checkFilesCount(this.props.filesCount)) filesCountOk = false;
    
    let fileCountInfo = interpolate(_("%(count)s files selected."), { count: this.props.filesCount });
    let gcp = this.getGcpFile();
    if (gcp){
      fileCountInfo = interpolate(_("%(count)s files and GCP file (%(name)s) selected."), { count: this.props.filesCount - 1, name: gcp.name });
    }

    return (
      <div className="new-task-panel theme-background-highlight">
        <div className="form-horizontal">
          <div className={this.state.inReview ? "disabled" : ""}>
            <p>{fileCountInfo} {_("Please check these additional options:")}</p>
            {this.props.filesCount === 999 && !this.state.dismissImageCountWarning ? 
            <div className="alert alert-warning alert-dismissible alert-images">
              <button type="button" className="close" title={_("Close")} onClick={() => this.setState({dismissImageCountWarning: true})}><span aria-hidden="true">&times;</span></button>
              <i className="fa fa-hand-point-right"></i> {_("Did you forget any images? When images exceed 1000, they are often stored inside multiple folders on the SD card.")}
            </div>
            : ""}

            {gcp && gcp._gcp && this.state.showMalformedGcpErrors ? 
            <div className="alert alert-warning alert-dismissible alert-images">
              <button type="button" className="close" title={_("Close")} onClick={() => this.setState({showMalformedGcpErrors: false})}><span aria-hidden="true">&times;</span></button>
              <div dangerouslySetInnerHTML={{__html: interpolate(_("Whoops! It looks like your GCP file is not formatted properly: %(errors)s See %(link)s for information on the GCP file format"), {
                link: `<a href="${window.__gcpDocsLink}" target="_blank">${_("GCP File")}</a>`,
                errors: "<ul>" + gcp._gcp.errors.map(err => `<li>${err}</li>`) + "</ul>"
              })}}></div>
            </div> : ""}
            

            {!filesCountOk ? 
            <div className="alert alert-warning">
              {interpolate(_("Number of files selected exceeds the maximum of %(count)s allowed on this processing node."), { count: this.taskForm.selectedNodeMaxImages() })}
              <button onClick={this.props.onCancel} type="button" className="btn btn-xs btn-primary redo">
                <span><i className="glyphicon glyphicon-remove-circle"></i> {_("Cancel")}</span>
              </button>
            </div>
            : ""}

            {this.state.showMapPreview ? <MapPreview 
              getFiles={this.props.getFiles}
              onPolygonChange={this.handlePolygonChange}
              onImagesBboxChanged={this.handleImagesBboxChange}
              basemaps={this.props.basemaps}
              ref={(domNode) => {this.mapPreview = domNode; }}
            /> : ""}

            <EditTaskForm
              selectedNode={Storage.getItem("last_processing_node") || "auto"}
              onFormLoaded={this.handleFormTaskLoaded}
              onFormChanged={this.handleFormChanged}
              inReview={this.state.inReview}
              suggestedTaskName={this.handleSuggestedTaskName}
              getCropPolygon={this.getCropPolygon}
              getGcpFile={this.getGcpFile}
              getPhotoPositions={this.getPhotoPositions}
              ref={(domNode) => { if (domNode) this.taskForm = domNode; }}
            />

            {this.state.editTaskFormLoaded && this.props.showAlign && this.state.showMapPreview && this.state.alignTasks.length > 0 ?
              <div>
                <div className="form-group">
                  <label className="col-sm-2 control-label">{_("Alignment")}</label>
                  <div className="col-sm-10">
                    <select className="form-control" disabled={this.state.loadingAlignTasks} value={this.state.alignTo} onChange={this.handleAlignToChanged}>
                      <option value="auto" key="auto">{this.state.loadingAlignTasks ? _("Loading...") : _("Automatic")}</option>
                      {this.state.alignTasks.map(t => 
                        <option value={t.id} key={t.id}>{t.name}</option>
                      )}
                    </select>
                  </div>
                </div>
              </div>
            : ""}

            {this.state.editTaskFormLoaded && this.props.showResize ?
              <div>
                <div className="form-group">
                  <label className="col-sm-2 control-label">{_("Resize Images")}</label>
                  <div className="col-sm-10">
                      <div className="btn-group">
                      <button type="button" className="btn btn-default dropdown-toggle" data-toggle="dropdown">
                          {ResizeModes.toHuman(this.state.resizeMode)} <span className="caret"></span>
                      </button>
                      <ul className="dropdown-menu">
                          {ResizeModes.all().map(mode =>
                          <li key={mode}>
                              <a href="javascript:void(0);" 
                                  onClick={this.setResizeMode(mode)}>
                                  <i style={{opacity: this.state.resizeMode === mode ? 1 : 0}} className="fa fa-check"></i> {ResizeModes.toHuman(mode)}</a>
                          </li>
                          )}
                      </ul>
                      </div>
                      <div className={"resize-control " + (this.state.resizeMode === ResizeModes.NO ? "hide" : "")}>
                      <input 
                          type="number" 
                          step="100"
                          className="form-control"
                          onChange={this.handleResizeSizeChange} 
                          value={this.state.resizeSize} 
                      />
                      <span>{_("px")}</span>
                      </div>
                  </div>
                </div>
                {this.state.items.map((Item, i) => <div key={i} className="form-group">
                  <Item taskInfo={this.state.taskInfo}
                        getFiles={this.props.getFiles}
                        filesCount={this.props.filesCount}
                      />
                </div>)}
              </div>
            : ""}

          </div>

          {this.state.editTaskFormLoaded ? 
            <div className="form-group">
              <div className="col-sm-offset-2 col-sm-10 text-right">
                {this.props.onCancel !== undefined && <button type="submit" className="btn btn-danger" onClick={this.cancel} style={{marginRight: 4}}><i className="glyphicon glyphicon-remove-circle"></i> {_("Cancel")}</button>}
                {this.state.loading ?
                  <button type="submit" className="btn btn-primary" disabled={true}><i className="fa fa-circle-notch fa-spin fa-fw"></i>{_("Loading…")}</button>
                  :
                  <button type="submit" className="btn btn-primary" onClick={this.save} disabled={this.props.filesCount < 1 || !filesCountOk}><i className="glyphicon glyphicon-saved"></i> {!this.state.inReview ? _("Review") : _("Start Processing")}</button>
                }
              </div>
            </div>
            : ""}
        </div>
      </div>
    );
  }
}

export default NewTaskPanel;

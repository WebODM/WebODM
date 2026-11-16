import '../css/ImportTaskPanel.scss';
import React from 'react';
import PropTypes from 'prop-types';
import Dropzone from '../vendor/dropzone';
import csrf from '../django/csrf';
import ErrorMessage from './ErrorMessage';
import UploadProgressBar from './UploadProgressBar';
import { _, interpolate } from '../classes/gettext';
import Trans from './Trans';

class ImportTaskPanel extends React.Component {
  static defaultProps = {
  };

  static propTypes = {
      onImported: PropTypes.func.isRequired,
      onCancel: PropTypes.func,
      projectId: PropTypes.number.isRequired
  };

  constructor(props){
    super(props);

    this.state = {
      error: "",
      typeUrl: false,
      uploading: false,
      importingFromUrl: false,
      progress: 0,
      bytesSent: 0,
      importUrl: ""
    };
  }

  defaultTaskName = () => {
    return interpolate(_("Task of %(date)s"), { date: new Date().toISOString() });
  }

  componentDidMount(){
    Dropzone.autoDiscover = false;

    if (this.dropzone){
      this.dz = new Dropzone(this.dropzone, {
          paramName: "file",
          url : `/api/projects/${this.props.projectId}/tasks/import`,
          parallelUploads: 1,
          maxFilesize: 2147483647,
          uploadMultiple: false,
          acceptedFiles: "application/zip,application/octet-stream,application/x-zip-compressed,multipart/x-zip",
          autoProcessQueue: true,
          createImageThumbnails: false,
          previewTemplate: '<div style="display:none"></div>',
          clickable: this.uploadButton,
          timeout: 2147483647,
          chunking: true,
          chunkSize: 8000000, // 8MB,
          retryChunks: true,
          retryChunksLimit: 20,
          headers: {
            [csrf.header]: csrf.token
          }
      });

      this.dz.on("error", (file) => {
          if (this.state.uploading) this.setState({error: _("Cannot upload file. Check your internet connection and try again.")});
        })
        .on("sending", () => {
          this.setState({typeUrl: false, uploading: true, totalCount: 1});
        })
        .on("reset", () => {
          this.setState({uploading: false, progress: 0, totalBytes: 0, totalBytesSent: 0});
        })
        .on("uploadprogress", (file, progress, bytesSent) => {
            if (progress == 100) return; // Workaround for chunked upload progress bar jumping around
            this.setState({
              progress,
              totalBytes: file.size,
              totalBytesSent: bytesSent
            });
        })
        .on("sending", (file, xhr, formData) => {
          // Safari does not have support for has on FormData
          // as of December 2017
          if (!formData.has || !formData.has("name")) formData.append("name", this.defaultTaskName());
        })
        .on("complete", (file) => {
          if (file.status === "success"){
            this.setState({uploading: false});
            try{
              let response = JSON.parse(file.xhr.response);
              if (!response.id) throw new Error(`Expected id field, but none given (${response})`);
              this.props.onImported();
            }catch(e){
              this.setState({error: interpolate(_('Invalid response from server: %(error)s'), { error: e.message})});
            }
          }else{
            this.setState({uploading: false, error: _("An error occured while uploading the file. Please try again.")});
          }
        });
    }
  }

  cancel = (e) => {
    this.cancelUpload();
    this.props.onCancel();
  }

  cancelUpload = (e) => {
    this.setState({uploading: false});
    setTimeout(() => {
      this.dz.removeAllFiles(true);
    }, 0);
  }

  handleImportFromUrl = () => {
    this.setState({typeUrl: !this.state.typeUrl});
  }

  handleCancelImportFromURL = () => {
    this.setState({typeUrl: false});
  }

  handleChangeImportUrl = (e) => {
    this.setState({importUrl: e.target.value});
  }

  handleConfirmImportUrl = () => {
    this.setState({importingFromUrl: true});

    $.post(`/api/projects/${this.props.projectId}/tasks/import`,
      {
        url: this.state.importUrl,
        name: this.defaultTaskName()
      }
    ).done(json => {
      this.setState({importingFromUrl: false});

      if (json.id){
        this.props.onImported();
      }else{
        this.setState({error: json.error || interpolate(_("Invalid JSON response: %(error)s"), {error: JSON.stringify(json)})});
      }
    })
    .fail((e) => {
      let error = _("Cannot import from URL. Check your internet connection.");
      if (e && e.responseJSON && Array.isArray(e.responseJSON) && e.responseJSON.length && typeof e.responseJSON[0] === 'string'){
        error = e.responseJSON[0];
      }
      this.setState({importingFromUrl: false, error});
    });
  }

  setRef = (prop) => {
    return (domNode) => {
      if (domNode != null) this[prop] = domNode;
    }
  }

  render() {
    return (
      <div ref={this.setRef("dropzone")} className="import-task-panel theme-background-highlight">
        <div className="form-horizontal">
          <ErrorMessage bind={[this, 'error']} />

          <button type="button" className="close theme-color-primary" title={_("Close")} onClick={this.cancel}><span aria-hidden="true">&times;</span></button>
          <h4>{_("Import Assets or Backups")}</h4>
          <p><Trans params={{arrow: '<i class="glyphicon glyphicon-arrow-right"></i>'}}>{_("You can import .zip files that have been exported from existing tasks via Download %(arrow)s All Assets | Backup.")}</Trans></p>
          
          <button disabled={this.state.uploading}
                  type="button" 
                  className="btn btn-primary"
                  ref={this.setRef("uploadButton")}>
            <i className="glyphicon glyphicon-upload"></i>
            {_("Upload a File")}
          </button>
          <button disabled={this.state.uploading}
                  type="button" 
                  className="btn btn-primary"
                  onClick={this.handleImportFromUrl}
                  ref={this.setRef("importFromUrlButton")}>
            <i className="glyphicon glyphicon-cloud-download"></i>
            {_("Import From URL")}
          </button>

          {this.state.typeUrl ? 
            <div className="form-inline">
              <div className="form-group">
                <input disabled={this.state.importingFromUrl} onChange={this.handleChangeImportUrl} size="45" type="text" className="form-control" placeholder="http://" value={this.state.importUrl} />
                <button onClick={this.handleConfirmImportUrl}
                        disabled={this.state.importUrl.length < 4 || this.state.importingFromUrl} 
                        className="btn-import btn btn-primary"><i className="glyphicon glyphicon-cloud-download"></i> {_("Import")}</button>
              </div>
            </div> : ""}

          {this.state.uploading ? <div>
            <UploadProgressBar {...this.state}/>
            <button type="button"
                    className="btn btn-danger btn-sm" 
                    onClick={this.cancelUpload}>
              <i className="glyphicon glyphicon-remove-circle"></i>
              {_("Cancel Upload")}
            </button> 
          </div> : ""}
        </div>
      </div>
    );
  }
}

export default ImportTaskPanel;

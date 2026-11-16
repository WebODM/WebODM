import '../css/ImportExternalPanel.scss';
import React from 'react';
import PropTypes from 'prop-types';
import Dropzone from '../vendor/dropzone';
import csrf from '../django/csrf';
import ErrorMessage from './ErrorMessage';
import UploadProgressBar from './UploadProgressBar';
import { _, interpolate } from '../classes/gettext';
import $ from 'jquery';

const ASSET_TYPES = [
  { key: 'orthophoto', label: _('Orthophoto'), icon: 'fa fa-map', accept: '.tif', mimeTypes: 'image/tiff' },
  { key: 'dsm', label: _('Surface Model'), icon: 'fa fa-chart-area', accept: '.tif', mimeTypes: 'image/tiff' },
  { key: 'dtm', label: _('Terrain Model'), icon: 'fa fa-chart-area', accept: '.tif', mimeTypes: 'image/tiff' },
  { key: 'pointcloud', label: _('Point Cloud'), icon: 'fa fa-pointcloud', accept: '.laz,.las', mimeTypes: 'application/vnd.laszip,application/vnd.las' },
  { key: 'texturedmodel', label: _('Textured Model'), icon: 'fab fa-connectdevelop', accept: '.glb', mimeTypes: 'gltf-binary' }
];

class ImportExternalPanel extends React.Component {
  static defaultProps = {};

  static propTypes = {
    onImported: PropTypes.func.isRequired,
    onCancel: PropTypes.func,
    projectId: PropTypes.number.isRequired
  };

  constructor(props) {
    super(props);
    this.state = {
      error: "",
      uploading: false,
      progress: 0,
      totalBytes: 0,
      totalBytesSent: 0,
      files: {}
    };
    this.dropzones = {};
    this.dzInstances = {};
    this.uploadUuid = null;
    this.fileProgress = {};
  }

  componentDidMount() {
    Dropzone.autoDiscover = false;
    ASSET_TYPES.forEach(asset => this.initDropzone(asset));
  }

  componentWillUnmount() {
    Object.values(this.dzInstances).forEach(dz => dz.destroy());
  }

  initDropzone = (asset) => {
    const element = this.dropzones[asset.key];
    if (!element) return;

    const dz = new Dropzone(element, {
      paramName: asset.key,
      url: `/api/projects/${this.props.projectId}/tasks/import/external/upload`,
      parallelUploads: 1,
      maxFilesize: 131072, // 128GB
      uploadMultiple: false,
      acceptedFiles: asset.mimeTypes + ',' + asset.accept,
      autoProcessQueue: false,
      createImageThumbnails: false,
      previewTemplate: '<div style="display:none"></div>',
      timeout: 2147483647,
      chunking: true,
      chunkSize: 8000000,
      retryChunks: true,
      retryChunksLimit: 10,
      maxFiles: 1,
      headers: {
        [csrf.header]: csrf.token
      }
    });

    dz.on("addedfile", (file) => {
      if (dz.files.length > 1) {
        dz.removeFile(dz.files[0]);
      }
      this.setState(prev => ({
        files: { ...prev.files, [asset.key]: file.name }
      }));
    });

    dz.on("removedfile", () => {
      this.setState(prev => {
        const files = { ...prev.files };
        delete files[asset.key];
        return { files };
      });
    });

    dz.on("sending", (file, xhr, formData) => {
      formData.append("uuid", this.uploadUuid);
    });

    dz.on("uploadprogress", (file, progress, bytesSent) => {
      if (progress === 100) return;
      this.fileProgress[asset.key] = { sent: bytesSent, total: file.size };
      this.updateTotalProgress();
    });

    dz.on("error", (file, errorMessage) => {
      file._retryCount = (file._retryCount || 0) + 1;
      if (file._retryCount < 10) {
        setTimeout(() => {
          file.status = Dropzone.QUEUED;
          dz.processQueue();
        }, 2000 * file._retryCount);
      } else {
        this.setState({ 
          error: _("Upload failed after multiple retries. Please check your connection and try again."),
          uploading: false 
        });
        this.cancelUpload();
      }
    });

    dz.on("success", (file) => {
      this.fileProgress[asset.key] = { sent: file.size, total: file.size };
      this.updateTotalProgress();
      this.checkAllUploadsComplete();
    });

    this.dzInstances[asset.key] = dz;
  };

  updateTotalProgress = () => {
    let totalBytes = 0;
    let totalBytesSent = 0;
    Object.values(this.fileProgress).forEach(p => {
      totalBytes += p.total;
      totalBytesSent += p.sent;
    });
    const progress = totalBytes > 0 ? (totalBytesSent / totalBytes) * 100 : 0;
    this.setState({ progress, totalBytes, totalBytesSent });
  };

  checkAllUploadsComplete = () => {
    const assetTypes = Object.keys(this.state.files);
    const allComplete = assetTypes.every(key => {
      const dz = this.dzInstances[key];
      return dz.files.length > 0 && dz.files[0].status === Dropzone.SUCCESS;
    });
    if (allComplete) {
      this.commitUpload();
    }
  };

  defaultTaskName = () => {
    return interpolate(_("Task of %(date)s"), { date: new Date().toISOString() });
  }

  initTask = () => {
    return $.ajax({
      url: `/api/projects/${this.props.projectId}/tasks/import/external/init`,
      type: 'POST',
      contentType: 'application/json',
      headers: {
      [csrf.header]: csrf.token
      },
    }).then(json => json.uuid);
  };

  commitUpload = (retryCount) => {
    retryCount = retryCount || 0;
    
    $.ajax({
      url: `/api/projects/${this.props.projectId}/tasks/import/external/commit`,
      data: JSON.stringify({ 
        uuid: this.uploadUuid,
        name: this.defaultTaskName()
      }),
      type: 'POST',
      contentType: 'application/json',
      headers: {
        [csrf.header]: csrf.token
      }
    }).done(() => {
      this.setState({ uploading: false, progress: 100 });
      this.props.onImported();
    }).fail((xhr) => {
      if (xhr.status === 400) {
        try {
          const errors = JSON.parse(xhr.responseText);
          if (Array.isArray(errors) && errors.length > 0) {
            this.setState({ 
              error: errors.join(", "), 
              uploading: false 
            });
            return;
          }
        } catch (e) {
          // Not valid JSON, continue with retry logic
        }
      }
      
      if (retryCount < 10) {
        setTimeout(() => {
          this.commitUpload(retryCount + 1);
        }, 2000 * (retryCount + 1));
      } else {
        this.setState({ 
          error: _("Failed to complete upload. Try again later."), 
          uploading: false 
        });
      }
    });
  };

  startUpload = () => {
    const assetTypes = Object.keys(this.state.files);
    if (assetTypes.length === 0) {
      this.setState({error: _("Select at least one file to upload.") });
      return;
    }

    // Don't allow a GLB to be uploaded alone
    // Always require a point cloud also
    if (assetTypes.indexOf("texturedmodel") !== -1 && assetTypes.indexOf("pointcloud") === -1){
      this.setState({error: _("A textured model requires also a point cloud to be properly displayed.") });
      return;
    }

    this.setState({ error: "", uploading: true, progress: 0 });
    this.fileProgress = {};

    assetTypes.forEach(key => {
      const dz = this.dzInstances[key];
      if (dz.files.length > 0) {
        this.fileProgress[key] = { sent: 0, total: dz.files[0].size };
      }
    });
    this.updateTotalProgress();

    this.initTask()
      .done(uuid => {
        this.uploadUuid = uuid;
        assetTypes.forEach(key => {
          this.dzInstances[key].processQueue();
        });
      })
      .fail(() => {
        this.setState({ 
          error: _("Failed to initialize upload. Try again later."), 
          uploading: false 
        });
      });
  };

  cancel = () => {
    this.cancelUpload();
    if (this.props.onCancel) this.props.onCancel();
  };

  cancelUpload = () => {
    this.setState({ uploading: false, progress: 0 });
    Object.values(this.dzInstances).forEach(dz => dz.removeAllFiles(true));
    this.fileProgress = {};
    this.uploadUuid = null;
  };

  setDropzoneRef = (key) => (node) => {
    if (node) this.dropzones[key] = node;
  };

  removeFile = (key) => {
    const dz = this.dzInstances[key];
    if (dz) dz.removeAllFiles(true);
  };

  render() {
    const { uploading, files } = this.state;
    const filesCount = Object.keys(files).length;
    const hasFiles = filesCount > 0;

    return (
      <div className="import-external-panel theme-background-highlight">
        <div className="form-horizontal">
          <ErrorMessage bind={[this, 'error']} />
          <button type="button" className="close theme-color-primary" title={_("Close")} onClick={this.cancel}>
            <span aria-hidden="true">&times;</span>
          </button>
          <h4><i className="fa fa-cloud-upload-alt"></i> {_("Import External Data")}</h4>
          <p>{_("Select files. At least one file is required.")}</p>

          <div className="asset-dropzones">
            {ASSET_TYPES.map(asset => (
              <div key={asset.key} className="asset-dropzone-wrapper">
                <div
                  ref={this.setDropzoneRef(asset.key)}
                  className={`theme-border-highlight-9 theme-border-highlight-7-hover theme-background-highlight theme-background-highlight-hover asset-dropzone ${files[asset.key] ? 'has-file' : ''} ${uploading ? 'disabled' : ''}`}
                >
                  <i className={`${asset.icon} asset-icon`}></i>
                  <div className="asset-label">{asset.label}</div>
                  {!files[asset.key] && <div className="asset-accept">{asset.accept}</div>}
                  {files[asset.key] && (
                    <div className="asset-filename">
                      <i className="fa fa-check-circle"></i> {files[asset.key]}
                      {!uploading && (
                        <button
                          type="button"
                          className="btn-remove-file"
                          onClick={(e) => { e.stopPropagation(); this.removeFile(asset.key); }}
                          title={_("Remove")}
                        >
                          <i className="fa fa-times"></i>
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {uploading ? (
            <div className="upload-progress-section">
              <UploadProgressBar totalCount={filesCount} {...this.state} />
              <button type="button" className="btn btn-danger btn-sm" onClick={this.cancelUpload}>
                <i className="fa fa-times-circle"></i> {_("Cancel Upload")}
              </button>
            </div>
          ) : (
            <button
              disabled={!hasFiles}
              type="button"
              className="btn btn-primary"
              onClick={this.startUpload}
            >
              <i className="fa fa-upload"></i> {_("Upload")}
            </button>
          )}
        </div>
      </div>
    );
  }
}

export default ImportExternalPanel;
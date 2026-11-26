import React from 'react';
import '../css/ShareButton.scss';
import SharePopup from './SharePopup';
import PropTypes from 'prop-types';
import { _ } from '../classes/gettext';

class ShareButton extends React.Component {
  static defaultProps = {
    task: null,
    project: null,
    popupPlacement: 'top',
    showVr: false,
  };
  static propTypes = {
    task: PropTypes.object,
    project: PropTypes.object,
    linksTarget: PropTypes.oneOf(['map', '3d']).isRequired,
    popupPlacement: PropTypes.string,
    queryParams: PropTypes.object,
    showVr: PropTypes.bool
  }

  constructor(props){
    super(props);

    this.state = { 
      showPopup: false,
      task: props.task,
      project: props.project
    };

    this.handleClick = this.handleClick.bind(this);
    this.handleTaskChanged = this.handleTaskChanged.bind(this);
    this.handleProjectChanged = this.handleProjectChanged.bind(this);
  }

  handleClick(e){
    this.setState({ showPopup: !this.state.showPopup });
  }

  hidePopup(){
    this.setState({showPopup: false});
  }

  handleTaskChanged(task){
    this.setState({task});
  }

  handleProjectChanged(project){
    this.setState({project});
  }

  render() {
    const popup = <SharePopup 
            task={this.state.task}
            taskChanged={this.handleTaskChanged}
            project={this.state.project}
            projectChanged={this.handleProjectChanged}
            
            placement={this.props.popupPlacement}
            linksTarget={this.props.linksTarget}
            queryParams={this.props.queryParams}
            showVr={this.props.showVr}
          />;
    
    const isPublic = this.state.task ? this.state.task.public : this.state.project.public;

    return (
      <div className="shareButton" onClick={e => { e.stopPropagation(); }}>
        {this.props.popupPlacement === 'top' && this.state.showPopup ? 
          popup : ""}
        <button 
          type="button"
          onClick={this.handleClick}
          title={_("Share")}
          className={"shareButton btn btn-sm " + (isPublic ? "btn-primary" : "btn-secondary")}>
          <i className="fa fa-share-alt"></i> {_("Share")}
        </button>
        {this.props.popupPlacement === 'bottom' && this.state.showPopup ? 
          popup : ""}
      </div>
    );
  }
}

export default ShareButton;

import React from 'react';
import PropTypes from 'prop-types';
import '../../css/modelview/Panel.scss';
import { _ } from '../../classes/gettext';

class HistoryPanel extends React.Component{
  static propTypes = {
    history: PropTypes.array.isRequired,
    index: PropTypes.number.isRequired,
    onRestore: PropTypes.func.isRequired,
    onClose: PropTypes.func.isRequired
  }

  render(){
    const { history, index } = this.props;

    return (<div className="mv-panel">
      <div className="mv-panel-toolbar">
        <button type="button" className="mv-panel-action" disabled={index <= 0}
                onClick={() => this.props.onRestore(index - 1)}><i className="mv-icon mv-icon-undo"></i> {_("Undo")}</button>
        <button type="button" className="mv-panel-action" disabled={index >= history.length - 1}
                onClick={() => this.props.onRestore(index + 1)}>{_("Redo")} <i className="mv-icon mv-icon-redo"></i></button>
        <button type="button" className="mv-panel-btn" title={_("Close")} onClick={this.props.onClose}><i className="mv-icon mv-icon-close"></i></button>
      </div>

      <div className="mv-panel-body">
        {history.length <= 1 ? <div className="mv-panel-empty">{_("No history")}</div> : ""}
        {history.map((entry, i) => i === 0 ? null :
        <div key={i} className={"mv-tree-row mv-history-row " + (i === index ? "selected" : "") + (i > index ? " undone" : "")}
             onClick={() => this.props.onRestore(i)}>
          <span className="mv-tree-label">{entry.label}</span>
        </div>)}
      </div>
    </div>);
  }
}

export default HistoryPanel;

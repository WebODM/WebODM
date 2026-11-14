import SystemJS from 'SystemJS';

const versioned = dep => {
  const version = (window.PluginVersions || {})[dep.split("/")[0]];
  if (!version || dep.indexOf("?") !== -1) return dep;

  const url = `${dep}?v=${encodeURIComponent(version)}`;
  return /\.css$/i.test(dep) ? `${url}!css` : url;
};

export default class ApiFactory{
  // @param events {EventEmitter}
  constructor(events){
    this.events = events; 
  }

  // @param api {Object}
  create(api){
    // Adds two functions to obj
    // - eventName
    // - triggerEventName
    // We could just use events, but methods
    // are more robust as we can detect more easily if 
    // things break

    const addEndpoint = (obj, eventName, preTrigger = () => {}) => {
      const emitResponse = response => {
        // Timeout needed for modules that have no dependencies
        // and load synchronously. Gives time to setup the listeners.
        setTimeout(() => {
          this.events.emit(`${api.namespace}::${eventName}::Response`, response);
        }, 0);
      };

      obj[eventName] = (callbackOrDeps, callbackOrUndef) => {
        if (Array.isArray(callbackOrDeps)){
          // Deps
          // Load dependencies, then raise event as usual
          // by appending the dependencies to the argument list
          this.events.addListener(`${api.namespace}::${eventName}`, args => {
            Promise.all(callbackOrDeps.map(dep => SystemJS.import(versioned(dep))))
              .then((...deps) => {
                
                // For each dependency, see if it exports a default module (ES6 style)
                // if it does, export just the default module, otherwise export all modules
                deps = deps.map(dep => {
                    return dep.map(exp => exp.default ? exp.default : exp);
                });

                const response = {
                  result: callbackOrUndef(...(Array.from([args]).concat(...deps))),
                  placeholder: args._placeholder
                };
                emitResponse(response);
              });
            });
        }else{
          // Callback
          this.events.addListener(`${api.namespace}::${eventName}`, args => {
            const response = {
              result: callbackOrDeps(args),
              placeholder: args._placeholder
            };
            emitResponse(response);
          });
        }
      }

      const triggerEventName = "trigger" + eventName[0].toUpperCase() + eventName.slice(1);

      obj[triggerEventName] = (args, responseCb) => {
        if (!args) args = {};
        args._placeholder = {};
        
        preTrigger(args, responseCb);
        if (responseCb && this.events.listeners(`${api.namespace}::${eventName}`).length > 0){
          this.events.addListener(`${api.namespace}::${eventName}::Response`, response => {
            // Give time to all listeners to receive the replies
            // then remove the listener to avoid sending duplicate responses
            const curSub = this.events._currentSubscription;

            setTimeout(() => {
              curSub.remove();
            }, 0);

            if (response.placeholder === args._placeholder) responseCb(response.result);
          });
        }
        this.events.emit(`${api.namespace}::${eventName}`, args);
      };
    }

    let obj = {};
    api.endpoints.forEach(endpoint => {
      if (!Array.isArray(endpoint)) endpoint = [endpoint];
      addEndpoint(obj, ...endpoint);
    });

    if (api.helpers){
      obj = Object.assign(obj, api.helpers);
    }

    // Handle syncronous function on/off/export
    (api.functions || []).forEach(func => {
      let callbacks = [];
      obj[func] = (...args) => {
        for (let i = 0; i < callbacks.length; i++){
          if ((callbacks[i])(...args)) return true;
        }
        return false;
      };

      const onName = "on" + func[0].toUpperCase() + func.slice(1);
      const offName = "off" + func[0].toUpperCase() + func.slice(1);
      obj[onName] = f => {
        callbacks.push(f);
      };
      obj[offName] = f => {
        callbacks = callbacks.filter(cb => cb !== f);
      };
    });

    return obj;
  }

}


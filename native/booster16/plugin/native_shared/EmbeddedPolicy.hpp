#pragma once
// Python.h precedes Qt headers: Qt's slots macro conflicts with Python slots.
#include <Python.h>
#include <QJsonObject>
#include <QJsonArray>
#include <QJsonDocument>
#include <QElapsedTimer>
#include <QFileInfo>
#include <cmath>
#include <cstdio>
#include <limits>
#include <stdexcept>
#include <thread>
#ifdef __linux__
#include <dlfcn.h>
#endif

// Shared-process computation, not RPC/IPC. Existing scene adapter's typed value
// tree is converted to CPython objects directly: no JSON strings, pipe or child.
class EmbeddedPolicy
{
  struct Ref {
    PyObject* p;
    explicit Ref(PyObject* p=nullptr):p(p){}
    ~Ref(){Py_XDECREF(p);}
    Ref(const Ref&)=delete;
    Ref& operator=(const Ref&)=delete;
    PyObject* release(){auto* r=p;p=nullptr;return r;}
  };
  struct Gil {
    PyGILState_STATE state=PyGILState_Ensure();
    ~Gil(){PyGILState_Release(state);}
  };
  inline static bool initializedHere=false;
  inline static QString runtimeExecutable;
  std::thread::id owner=std::this_thread::get_id();
  PyObject* module=nullptr;
  PyObject* backend=nullptr;
  void ownerOnly() const {
    if(std::this_thread::get_id()!=owner) throw std::runtime_error("Native policy called from a foreign thread");
  }
  static std::runtime_error error(const char* context) {
    PyObject *type=nullptr,*value=nullptr,*trace=nullptr;
    PyErr_Fetch(&type,&value,&trace);Ref a(type),b(value),c(trace);
    Ref text(value?PyObject_Str(value):nullptr);
    const char* detail=text.p?PyUnicode_AsUTF8(text.p):nullptr;
    return std::runtime_error(std::string(context)+(detail?std::string(": ")+detail:""));
  }
  static PyObject* toPython(const QJsonValue& value) {
    if(value.isObject()) {
      Ref dict(PyDict_New()); if(!dict.p)throw error("dict allocation");
      const auto object=value.toObject();
      for(auto it=object.begin();it!=object.end();++it) {
        Ref v(toPython(it.value()));
        if(PyDict_SetItemString(dict.p,it.key().toUtf8().constData(),v.p)<0)throw error("dict item");
      }return dict.release();
    }
    if(value.isArray()) {
      const auto array=value.toArray();Ref list(PyList_New(array.size()));
      if(!list.p)throw error("list allocation");
      for(qsizetype i=0;i<array.size();++i) { auto* item=toPython(array[i]); if(!item)throw error("list item allocation"); PyList_SET_ITEM(list.p,i,item); }
      return list.release();
    }
    if(value.isString())return PyUnicode_FromString(value.toString().toUtf8().constData());
    if(value.isBool())return PyBool_FromLong(value.toBool());
    if(value.isDouble()) {
      double x=value.toDouble();if(!std::isfinite(x))throw std::runtime_error("Nonfinite native input");
      if(std::floor(x)==x && std::abs(x)<=9007199254740991.0)return PyLong_FromLongLong(static_cast<long long>(x));
      return PyFloat_FromDouble(x);
    }
    Py_INCREF(Py_None);return Py_None;
  }
  static QJsonValue fromPython(PyObject* value) {
    if(value==Py_None)return QJsonValue::Null;
    if(PyBool_Check(value))return value==Py_True;
    if(PyLong_Check(value)||PyFloat_Check(value)) {
      const double x=PyFloat_AsDouble(value);
      if(PyErr_Occurred())throw error("numeric output");
      if(!std::isfinite(x))throw std::runtime_error("Nonfinite native output");
      return x;
    }
    if(PyUnicode_Check(value)){const char* s=PyUnicode_AsUTF8(value);if(!s)throw error("string output");return QString::fromUtf8(s);}
    if(PyDict_Check(value)) {
      QJsonObject out;PyObject *key,*item;Py_ssize_t pos=0;
      while(PyDict_Next(value,&pos,&key,&item)) {
        if(!PyUnicode_Check(key))throw std::runtime_error("Nonstring output key");
        const char* k=PyUnicode_AsUTF8(key);if(!k)throw error("output key");out.insert(QString::fromUtf8(k),fromPython(item));
      }return out;
    }
    if(PyList_Check(value)||PyTuple_Check(value)) {
      QJsonArray out;const auto n=PySequence_Size(value);
      for(Py_ssize_t i=0;i<n;++i){Ref item(PySequence_GetItem(value,i));if(!item.p)throw error("sequence output");out.append(fromPython(item.p));}return out;
    }
    throw std::runtime_error("Unexpected native output type");
  }
public:
  EmbeddedPolicy()=default;
  EmbeddedPolicy(const EmbeddedPolicy&)=delete;
  EmbeddedPolicy& operator=(const EmbeddedPolicy&)=delete;
  ~EmbeddedPolicy() noexcept {try{stop();}catch(...) {}}
  void stop() {
    ownerOnly();if(!Py_IsInitialized())return;Gil gil;
    Py_CLEAR(backend);Py_CLEAR(module);
    // Never finalize CPython/PyTorch during module unload: worker/native extension
    // lifetime belongs to the process. Per-robot policy tensors are decref'd here.
  }
  void start(const QString& python,const QString& script) {
    ownerOnly();stop();
    if(!QFileInfo(python).isAbsolute()||!QFileInfo(python).isExecutable()||
       !QFileInfo(script).isAbsolute()||!QFileInfo(script).isFile())
      throw std::runtime_error("Absolute Python runtime and existing pinned backend required");
    if(Py_IsInitialized() && (!initializedHere || runtimeExecutable!=python))
      throw std::runtime_error("Foreign/different CPython runtime already active");
    if(!Py_IsInitialized()) {
#ifdef __linux__
      // Qt loads plugins locally; Python extension modules need the linked
      // CPython symbols globally visible. Retain this exact loaded library for
      // the process lifetime, not an arbitrary library supplied by the scene.
      Dl_info info{};
      if(!dladdr(reinterpret_cast<void*>(&Py_Initialize),&info) ||
         !dlopen(info.dli_fname,RTLD_NOW|RTLD_GLOBAL|RTLD_NOLOAD))
        throw std::runtime_error("Cannot retain linked CPython runtime globally");
#endif
      PyConfig config;PyConfig_InitIsolatedConfig(&config);
      const auto path=python.toUtf8();
      auto status=PyConfig_SetBytesString(&config,&config.program_name,path.constData());
      if(!PyStatus_Exception(status))status=PyConfig_SetBytesString(&config,&config.executable,path.constData());
      if(!PyStatus_Exception(status))status=Py_InitializeFromConfig(&config);
      if(PyStatus_Exception(status)){std::string message=status.err_msg?status.err_msg:"CPython initialization failed";PyConfig_Clear(&config);throw std::runtime_error(message);}
      PyConfig_Clear(&config);initializedHere=true;runtimeExecutable=python;
      PyEval_SaveThread();
    }
    Gil gil;
    Ref imported(PyModule_New("booster_native_policy_backend"));if(!imported.p)throw error("backend module");
    auto* globals=PyModule_GetDict(imported.p);
    Ref file(PyUnicode_FromString(script.toUtf8().constData()));
    if(!file.p||PyDict_SetItemString(globals,"__file__",file.p)<0)throw error("backend path");
    FILE* source=fopen(script.toUtf8().constData(),"r");if(!source)throw std::runtime_error("Backend read failed");
    Ref executed(PyRun_FileExFlags(source,script.toUtf8().constData(),Py_file_input,globals,globals,1,nullptr));
    if(!executed.p)throw error("Pinned backend import");
    auto* cls=PyDict_GetItemString(globals,"OfficialK1Backend");
    if(!cls||!PyCallable_Check(cls))throw std::runtime_error("Missing official backend class");
    Ref instance(PyObject_CallNoArgs(cls));if(!instance.p)throw error("Official model initialization");
    module=imported.release();backend=instance.release();
  }
  QJsonObject exchange(const QJsonObject& request,int timeoutMs) {
    ownerOnly();if(!backend)throw std::runtime_error("Native policy not initialized");
    if(timeoutMs<=0)throw std::runtime_error("Positive soft execution budget required");
    Gil gil;QElapsedTimer timer;timer.start();Ref result;
    const auto op=request.value("op").toString();
    if(op=="reset") {
      Ref epoch(toPython(request.value("epoch"))),origin(toPython(request.value("origin_ns")));
      result.p=PyObject_CallMethod(backend,"reset","OO",epoch.p,origin.p);
    }else if(op=="step") {
      Ref frame(toPython(request.value("frame")));
      result.p=PyObject_CallMethod(backend,"step","O",frame.p);
    }else throw std::runtime_error("Unsupported native policy operation");
    if(!result.p)throw error("Official policy call");
    // Soft overrun detection only: in-process PyTorch cannot safely be killed.
    // The simulator pauses on return before granting another physics-step lease.
    if(timer.elapsed()>timeoutMs)throw std::runtime_error("Native policy soft budget exceeded (call completed)");
    auto out=fromPython(result.p);
    if(!out.isObject())throw std::runtime_error("Expected official policy object");
    return {{"ok",true},{"robot_id",request.value("robot_id")},{"result",out}};
  }
};

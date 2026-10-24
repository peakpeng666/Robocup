#pragma once
#include <QProcess>
#include <QJsonObject>
#include <QJsonDocument>
#include <QElapsedTimer>
#include <QFileInfo>
#include <stdexcept>

// Synchronous, simulation-time lockstep transport. Not a realtime scheduler.
class PolicyProcess
{
  QProcess child;
  QByteArray pending;
public:
  ~PolicyProcess() noexcept { try { stop(); } catch(...) {} }
  void stop()
  {
    child.closeWriteChannel();
    if(child.state()!=QProcess::NotRunning && !child.waitForFinished(500))
    {
      child.terminate();
      if(!child.waitForFinished(500)) { child.kill(); child.waitForFinished(1000); }
    }
    pending.clear();
  }
  void start(const QString& python,const QString& script)
  {
    stop();
    if(!QFileInfo(python).isAbsolute() || !QFileInfo(python).isExecutable() ||
       !QFileInfo(script).isAbsolute() || !QFileInfo(script).isFile())
      throw std::runtime_error("Provide absolute existing BOOSTER_PYTHON and BOOSTER_POLICY_SCRIPT paths");
    child.setProcessChannelMode(QProcess::SeparateChannels);
    child.setProgram(python);
    child.setArguments({"-B",script}); // No shell, command interpolation or robot service.
    child.start();
    if(!child.waitForStarted(5000)) throw std::runtime_error("Python backend failed to start");
  }
  QJsonObject exchange(const QJsonObject& request,int timeoutMs)
  {
    if(child.state()!=QProcess::Running) throw std::runtime_error("Policy process not running");
    const QByteArray line=QJsonDocument(request).toJson(QJsonDocument::Compact)+'\n';
    if(child.write(line)!=line.size()) throw std::runtime_error("Policy pipe write failed");
    QElapsedTimer timer;timer.start();
    while(true)
    {
      pending+=child.readAllStandardOutput();
      // Drain diagnostics to avoid blocking the child. Keep bounded, no credentials.
      const QByteArray diagnostics=child.readAllStandardError();
      if(!diagnostics.isEmpty()) fprintf(stderr,"%s",diagnostics.constData());
      if(pending.size()>1024*1024) throw std::runtime_error("Policy reply exceeds 1MiB");
      const auto end=pending.indexOf('\n');
      if(end>=0)
      {
        const QByteArray reply=pending.left(end);pending.remove(0,end+1);
        if(!pending.isEmpty()) throw std::runtime_error("Unexpected unsolicited policy reply");
        QJsonParseError error;
        auto document=QJsonDocument::fromJson(reply,&error);
        if(error.error!=QJsonParseError::NoError || !document.isObject())
          throw std::runtime_error("Malformed policy JSON response");
        auto object=document.object();
        if(!object.value("ok").isBool() || !object.value("ok").toBool())
          throw std::runtime_error(("Policy rejected request: "+object.value("message").toString()).toStdString());
        return object;
      }
      const int remaining=timeoutMs-static_cast<int>(timer.elapsed());
      if(remaining<=0) throw std::runtime_error("Policy response timeout");
      if(child.state()!=QProcess::Running) throw std::runtime_error("Policy child exited before reply");
      child.waitForReadyRead(remaining);
    }
  }
};

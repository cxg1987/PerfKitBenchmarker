# Copyright 2014 Google Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Runs SpecCPU2006.

From SpecCPU2006's documentation:
The SPEC CPU2006 benchmark is SPEC's industry-standardized, CPU-intensive
benchmark suite, stressing a system's processor, memory subsystem and compiler.

SpecCPU2006 homepage: http://www.spec.org/cpu2006/
"""

import os
import re

import gflags as flags
import logging
from perfkitbenchmarker import errors

FLAGS = flags.FLAGS

flags.DEFINE_enum('benchmark_subset', 'int', ['int', 'fp', 'all'],
                  'specify a subset of benchmarks to run: int, fp, all')

BENCHMARK_INFO = {'name': 'speccpu2006',
                  'description': 'Run Spec CPU2006',
                  'scratch_disk': True,
                  'num_machines': 1}

DATA_DIR = 'data'
SPECCPU2006_TAR = 'cpu2006v1.2.tgz'
SPECCPU2006_DIR = 'cpu2006'


def GetInfo():
  return BENCHMARK_INFO


def Prepare(benchmark_spec):
  """Install SpecCPU2006 on the target vm.

  Args:
    benchmark_spec: The benchmark specification. Contains all data that is
        required to run the benchmark.
  """
  vms = benchmark_spec.vms
  vm = vms[0]
  logging.info('prepare SpecCPU2006 on %s', vm)
  vm.InstallPackage('build-essential')
  vm.InstallPackage('gfortran')
  tar_file_path = os.path.join(DATA_DIR, SPECCPU2006_TAR)
  local_tar_file_path = tar_file_path
  if not os.path.isfile(local_tar_file_path):
    logging.error('Please provide %s under %s directory before'
                  ' running SpecCPU2006 benchmark.', SPECCPU2006_TAR, DATA_DIR)
    raise errors.Benchmarks.PrepareException(
        '%s not fount.' % local_tar_file_path)
  vm.tar_file_path = os.path.join(vm.GetScratchDir(), SPECCPU2006_TAR)
  vm.spec_dir = os.path.join(vm.GetScratchDir(), SPECCPU2006_DIR)
  vm.RemoteCommand('chmod 777 %s' % vm.GetScratchDir())
  vm.PushFile(local_tar_file_path, vm.GetScratchDir())
  vm.RemoteCommand('cd %s && tar xvfz %s' % (vm.GetScratchDir(),
                                             SPECCPU2006_TAR))


def ExtractScore(stdout, vm):
  """Exact the Spec (int|fp) score from stdout.

  Args:
    stdout: stdout from running RemoteCommand.
    vm: The vm instance where Spec CPU2006 was run.

  Sample input for SPECint:
      ...
      ...
      =============================================
      400.perlbench    9770        417       23.4 *
      401.bzip2        9650        565       17.1 *
      403.gcc          8050        364       22.1 *
      429.mcf          9120        364       25.1 *
      445.gobmk       10490        499       21.0 *
      456.hmmer        9330        491       19.0 *
      458.sjeng       12100        588       20.6 *
      462.libquantum  20720        468       44.2 *
      464.h264ref     22130        700       31.6 *
      471.omnetpp      6250        349       17.9 *
      473.astar        7020        482       14.6 *
      483.xalancbmk    6900        248       27.8 *
       Est. SPECint(R)_base2006              22.7

  Sample input for SPECfp:
      ...
      ...
      =============================================
      410.bwaves      13590        717      19.0  *
      416.gamess      19580        923      21.2  *
      433.milc         9180        480      19.1  *
      434.zeusmp       9100        600      15.2  *
      435.gromacs      7140        605      11.8  *
      436.cactusADM   11950       1289       9.27 *
      437.leslie3d     9400        859      10.9  *
      444.namd         8020        504      15.9  *
      447.dealII      11440        409      28.0  *
      450.soplex       8340        272      30.6  *
      453.povray       5320        231      23.0  *
      454.calculix     8250        993       8.31 *
      459.GemsFDTD    10610        775      13.7  *
      465.tonto        9840        565      17.4  *
      470.lbm         13740        365      37.7  *
      481.wrf         11170        788      14.2  *
      482.sphinx3     19490        668      29.2  *
       Est. SPECfp(R)_base2006              17.5

  Returns:
      A list of samples in the form of 3 or 4 tuples. The tuples contain
          the sample metric (string), value (float), and unit (string).
          If a 4th element is included, it is a dictionary of sample
          metadata.
  """
  results = []

  re_begin_section = re.compile('^={1,}')
  re_end_section = re.compile(r'Est. (SPEC.*_base2006)\s*(\S*)')
  result_section = []
  in_result_section = False

  # Extract the summary section
  for line in stdout.splitlines():
    if in_result_section:
      result_section.append(line)
    # search for begin of result section
    match = re.search(re_begin_section, line)
    if match:
      assert not in_result_section
      in_result_section = True
      continue
    # search for end of result section
    match = re.search(re_end_section, line)
    if match:
      assert in_result_section
      spec_name = str(match.group(1))
      spec_score = float(match.group(2))
      in_result_section = False
      # remove the final SPEC(int|fp) score, which has only 2 columns.
      result_section.pop()

  metadata = {'machine_type': vm.machine_type, 'num_cpus': vm.num_cpus}
  results.append((spec_name, spec_score, '', metadata))

  for benchmark in result_section:
    # ignore failed runs
    if re.search('NR', benchmark):
      continue
    # name, ref_time, time, score, misc
    name, _, _, score, _ = benchmark.split()
    results.append((str(name), float(score), '', metadata))

  return results


def ParseOutput(vm):
  """Parses the output from Spec CPU2006.

  Args:
    vm: The vm instance where Spec CPU2006 was run.

  Returns:
    A list of samples to be published (in the same format as Run() returns).
  """
  results = []

  log_files = []
  # FIXME(liquncheng): Only reference runs generate SPEC scores. The log
  # id is hardcoded as 001, which might change with different runspec
  # parameters. Spec CPU 2006 will generate different logs for build, test
  # run, training run and ref run.
  if FLAGS.benchmark_subset in ('int', 'all'):
    log_files.append('CINT2006.001.ref.txt')
  if FLAGS.benchmark_subset in ('fp', 'all'):
    log_files.append('CFP2006.001.ref.txt')

  for log in log_files:
    stdout, _ = vm.RemoteCommand('cat %s/result/%s' % (vm.spec_dir, log),
                                 should_log=True)
    results.extend(ExtractScore(stdout, vm))

  return results


def Run(benchmark_spec):
  """Run SpecCPU2006 on the target vm.

  Args:
    benchmark_spec: The benchmark specification. Contains all data that is
        required to run the benchmark.

  Returns:
    A list of samples in the form of 3 or 4 tuples. The tuples contain
        the sample metric (string), value (float), and unit (string).
        If a 4th element is included, it is a dictionary of sample
        metadata.
  """
  vms = benchmark_spec.vms
  vm = vms[0]
  logging.info('SpecCPU2006 running on %s', vm)
  num_cpus = vm.num_cpus
  vm.RemoteCommand('cd %s; . ./shrc; ./bin/relocate; . ./shrc; rm -rf result; '
                   'runspec --config=linux64-x64-gcc47.cfg --tune=base '
                   '--size=ref --noreportable -rate %s %s '
                   % (vm.spec_dir, num_cpus, FLAGS.benchmark_subset))
  logging.info('SpecCPU2006 Results:')
  return ParseOutput(vm)


def Cleanup(benchmark_spec):
  """Cleanup SpecCPU2006 on the target vm.

  Args:
    benchmark_spec: The benchmark specification. Contains all data that is
        required to run the benchmark.
  """
  vms = benchmark_spec.vms
  vm = vms[0]
  vm.RemoteCommand('rm -rf %s' % vm.spec_dir)
  vm.RemoteCommand('rm -f %s' % vm.tar_file_path)
  vm.UninstallPackage('build-essential')
  vm.UninstallPackage('gfortran')